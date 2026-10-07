from decimal import Decimal
from types import SimpleNamespace
from contextlib import nullcontext
from unittest.mock import patch

from django.conf import settings
from django.contrib.messages.storage.fallback import FallbackStorage
from django.contrib.messages.constants import ERROR, SUCCESS
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import RequestFactory
from django.test import SimpleTestCase
from django.template.loader import get_template, render_to_string
from django.urls import resolve

from .models import Customer
from .views import (
    _canonical_excel_headers,
    _filter_passengers_by_name,
    _parse_flat_price_range,
    calculate_discounted_net,
    excel_upload,
)


class FlatPriceRuleTests(SimpleTestCase):
    @patch("core.views.read")
    def test_matching_range_percentage_applies_at_both_boundaries(self, read_rules):
        read_rules.return_value = [
            {
                "airline": "AirAsia",
                "fare_type": "Economy Class",
                "flat_price": "10000 - 50000",
                "percentage": 10,
                "status": "Active",
            },
            {
                "airline": "AirAsia",
                "fare_type": "Economy Class",
                "flat_price": "",
                "percentage": 3,
                "status": "Active",
            },
        ]

        for amount in (Decimal("10000"), Decimal("50000")):
            with self.subTest(amount=amount):
                net_amount, percentage, _ = calculate_discounted_net(
                    amount, "AirAsia", "Economy Class"
                )
                self.assertEqual(percentage, Decimal("10"))
                self.assertEqual(net_amount, amount * Decimal("0.9"))

    @patch("core.views.read")
    def test_amount_outside_range_uses_unbounded_fallback_rule(self, read_rules):
        read_rules.return_value = [
            {
                "airline": "AirAsia",
                "fare_type": "Economy Class",
                "flat_price": "10000 - 50000",
                "percentage": 10,
                "status": "Active",
            },
            {
                "airline": "AirAsia",
                "fare_type": "Economy Class",
                "flat_price": "",
                "percentage": 3,
                "status": "Active",
            },
        ]

        net_amount, percentage, _ = calculate_discounted_net(
            Decimal("50001"), "AirAsia", "Economy Class"
        )

        self.assertEqual(percentage, Decimal("3"))
        self.assertEqual(net_amount, Decimal("48500.97"))

    def test_flat_price_range_rejects_reversed_bounds(self):
        with self.assertRaises(ValueError):
            _parse_flat_price_range("50000 - 10000")


class PassengerNameSearchTests(SimpleTestCase):
    def test_search_filters_by_passenger_name_case_insensitively(self):
        bookings = [
            {"passenger_name": "Anita Rao"},
            {"passenger_name": "Mohan Das"},
        ]

        self.assertEqual(
            _filter_passengers_by_name(bookings, "ANITA"),
            [bookings[0]],
        )


class UpdatedTemplateTests(SimpleTestCase):
    def test_updated_templates_compile(self):
        for template_name in (
            "bookings.html",
            "client_portal.html",
            "coupons.html",
            "customers.html",
            "excel_upload.html",
            "rules.html",
        ):
            with self.subTest(template=template_name):
                get_template(template_name)


class ExcelUploadMessageTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def make_request(self, file_content=b"workbook"):
        request = self.factory.post(
            "/excel-upload/",
            {"excel_file": SimpleUploadedFile("bookings.xlsx", file_content)},
        )
        request.session = {"user_id": "admin"}
        request._messages = FallbackStorage(request)
        return request

    @patch("openpyxl.load_workbook")
    def test_invalid_excel_shows_red_failure_message(self, load_workbook):
        load_workbook.return_value.active.__getitem__.return_value = [
            SimpleNamespace(value="S PNR"),
        ]

        request = self.make_request()
        response = excel_upload(request)

        self.assertEqual(response.status_code, 302)
        messages = list(request._messages)
        self.assertEqual(messages[0].message, "Something Went Wrong")
        self.assertEqual(messages[0].level_tag, "error")
        self.assertIn("Missing required Excel columns", messages[1].message)

    @patch("core.views.calculate_discounted_net", return_value=(Decimal("90.00"), Decimal("10"), {}))
    @patch("core.views.Booking.objects.bulk_create")
    @patch(
        "core.views.Customer.objects.in_bulk",
        return_value={"CL-1001": Customer(id="CL-1001", name="Client")},
    )
    @patch("core.views.Booking.objects.values_list", return_value=[])
    @patch("core.views.transaction.atomic", return_value=nullcontext())
    @patch("openpyxl.load_workbook")
    def test_successful_excel_import_shows_green_success_message(
        self,
        load_workbook,
        _atomic,
        _existing_pnrs,
        _customers,
        _bulk_create,
        _calculate_discount,
    ):
        headers = [
            "S PNR", "Client ID", "Passenger Name", "Sector", "Booking Type",
            "Travel Type", "Airline Name", "Airline Type", "Airline PNR",
            "Net Amount", "Travel Start Date", "Travel End Date", "Booking Date",
        ]
        row = [
            "SPNR78901", "CL-1001", "Anita Rao", "MAA-DXB", "Web Booking",
            "Round Trip", "AirAsia", "Economy Class", "6E-XY789", "100",
            "2026-10-10", "2026-10-11", "2026-10-01",
        ]
        second_row = [
            "SPNR78902", "CL-1001", "Mohan Das", "DEL-BOM", "Agent Booking",
            "One Way", "IndiGo", "Business Class", "6E-XY790", "250",
            "2026-10-12", "2026-10-12", "2026-10-02",
        ]
        workbook = load_workbook.return_value
        workbook.active.__getitem__.return_value = [
            SimpleNamespace(value=header) for header in headers
        ]
        workbook.active.iter_rows.return_value = [tuple(row), tuple(second_row)]

        request = self.make_request()
        response = excel_upload(request)

        self.assertEqual(response.status_code, 302)
        messages = list(request._messages)
        self.assertEqual(messages[0].message, "Booking Added Successfully")
        self.assertEqual(messages[0].level_tag, "success")
        self.assertEqual(
            messages[1].message,
            "Excel upload complete: 2 booking(s) added and 0 booking(s) updated.",
        )
        created_bookings = _bulk_create.call_args.args[0]
        self.assertEqual(len(created_bookings), 2)
        self.assertEqual(
            [(booking.pnr, booking.passenger_name) for booking in created_bookings],
            [("SPNR78901", "Anita Rao"), ("SPNR78902", "Mohan Das")],
        )

    def test_django_templates_include_message_context_processor(self):
        processors = settings.TEMPLATES[0]["OPTIONS"]["context_processors"]
        self.assertIn("django.contrib.messages.context_processors.messages", processors)

    def test_excel_upload_page_renders_success_and_error_alerts(self):
        for level, text, css_class in (
            (SUCCESS, "Booking Added Successfully", "success"),
            (ERROR, "Something Went Wrong", "error"),
        ):
            with self.subTest(level=level):
                request = self.factory.get("/excel-upload/")
                request.session = {"user_id": "admin"}
                request.resolver_match = resolve("/excel-upload/")
                request._messages = FallbackStorage(request)
                request._messages.add(level, text)

                html = render_to_string(
                    "base.html",
                    {"current_user": "Administrator"},
                    request=request,
                )

                self.assertIn(f'class="alert {css_class}"', html)
                self.assertIn(text, html)

    def test_excel_upload_accepts_common_header_variations(self):
        self.assertEqual(
            _canonical_excel_headers(
                [
                    "PNR",
                    "Customer ID",
                    "Passenger Name",
                    "Sector",
                    "Booking Type",
                    "Travel Type",
                    "Airline",
                    "Fare Type",
                    "Airline PNR",
                    "Amount",
                    "Travel Date",
                    "End Date",
                    "Booked Date",
                    "Passenger ID",
                ]
            ),
            [
                "S PNR",
                "Client ID",
                "Passenger Name",
                "Sector",
                "Booking Type",
                "Travel Type",
                "Airline Name",
                "Airline Type",
                "Airline PNR",
                "Net Amount",
                "Travel Start Date",
                "Travel End Date",
                "Booking Date",
                "Passenger ID",
            ],
        )
