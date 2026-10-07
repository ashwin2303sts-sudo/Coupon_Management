from decimal import Decimal
from unittest.mock import patch

from django.test import SimpleTestCase
from django.template.loader import get_template

from .views import _filter_passengers_by_name, _parse_flat_price_range, calculate_discounted_net


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
