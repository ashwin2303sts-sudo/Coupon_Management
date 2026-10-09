from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
import logging
import json
from functools import wraps

from django.contrib import messages
from django.contrib.auth.hashers import check_password, make_password
from django.core.paginator import Paginator
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render, redirect
from django.views.decorators.http import require_POST
from django.db import transaction
from django.utils import timezone

from .decorators import admin_required
from .models import Coupon, Redemption, RedemptionAllocation, Ledger, Customer, Booking
from .storage import read, write, now, new_id, money, decimal_value, date_value, get_or_create_customer


AIRLINES = [
    "Air India", "Air India Express", "IndiGo", "SpiceJet", "Akasa Air",
    "Alliance Air", "Emirates", "Qatar Airways", "Etihad Airways",
    "Singapore Airlines", "Malaysia Airlines", "Thai Airways", "SriLankan Airlines",
    "British Airways", "Lufthansa", "Air France", "KLM Royal Dutch Airlines",
    "Turkish Airlines", "Swiss International Air Lines", "Austrian Airlines",
    "Finnair", "Virgin Atlantic", "American Airlines", "Delta Air Lines",
    "United Airlines", "Air Canada", "Qantas", "Cathay Pacific", "Japan Airlines",
    "ANA (All Nippon Airways)", "Korean Air", "China Airlines", "EVA Air",
    "AirAsia", "AirAsia X", "Scoot", "VietJet Air", "Vietnam Airlines",
    "Garuda Indonesia", "Batik Air", "Oman Air", "Gulf Air", "Kuwait Airways",
    "Saudia", "flydubai", "Air Arabia", "Azerbaijan Airlines", "Ethiopian Airlines",
    "Kenya Airways", "South African Airways", "ANY AIRLINE",
]
AIRLINE_TYPES = ["Economy Class", "Premium Class", "Business Class", "ANY CLASS"]
BOOKING_METHODS = ["Web Booking", "Mobile App", "Agent Booking", "Offline/Counter"]
TRAVEL_TYPES = ["Round Trip", "One Way"]
logger = logging.getLogger(__name__)


def _normalise(value):
    return str(value or "").strip().casefold()


def _parse_flat_price_range(value):
    raw_value = str(value or "").strip().replace(",", "")
    if not raw_value or raw_value in {"0", "0.0", "0.00", "0.000", "0.0000"}:
        return None
    for separator in ("–", "—"):
        raw_value = raw_value.replace(separator, "-")
    parts = [part.strip() for part in raw_value.split("-")]
    if len(parts) != 2:
        raise ValueError("Enter a Flat Price range as minimum - maximum.")
    try:
        minimum, maximum = (Decimal(part) for part in parts)
    except InvalidOperation as exc:
        raise ValueError("Flat Price range must contain valid amounts.") from exc
    if not minimum.is_finite() or not maximum.is_finite() or minimum < 0 or maximum < minimum:
        raise ValueError("Flat Price range must be non-negative and the maximum must be at least the minimum.")
    return minimum, maximum


def _filter_passengers_by_name(bookings, query):
    query = str(query or "").strip().casefold()
    return [
        booking for booking in bookings
        if not query or query in str(booking.get("passenger_name", "")).casefold()
    ]


def _rule_matches(rule, airline, airline_type, base_amount=None):
    if str(rule.get("status", "Active")).casefold() != "active":
        return False
    rule_airline = str(rule.get("airline") or "ANY AIRLINE").strip()
    rule_type = str(rule.get("fare_type") or "ANY CLASS").strip()
    airline_ok = _normalise(rule_airline) in {_normalise(airline), "any airline"}
    type_ok = _normalise(rule_type) in {_normalise(airline_type), "any class"}
    if not airline_ok or not type_ok:
        return False
    try:
        price_range = _parse_flat_price_range(rule.get("flat_price"))
    except ValueError:
        return False
    if price_range is None:
        return True
    if base_amount is None:
        return False
    amount = decimal_value(base_amount)
    return price_range[0] <= amount <= price_range[1]


def _find_matching_rule(airline, airline_type, base_amount=None):
    rules = [r for r in read("rules") if _rule_matches(r, airline, airline_type, base_amount)]
    if not rules:
        return None
    # Prefer exact airline + exact class, then progressively broader fallbacks.
    def specificity(rule):
        score = 0
        if _normalise(rule.get("airline")) == _normalise(airline):
            score += 4
        if _normalise(rule.get("fare_type")) == _normalise(airline_type):
            score += 2
        price_range = _parse_flat_price_range(rule.get("flat_price"))
        return (
            score,
            price_range is not None,
            -(price_range[1] - price_range[0]) if price_range else Decimal(0),
        )
    return sorted(rules, key=specificity, reverse=True)[0]


def calculate_discounted_net(base_amount, airline, airline_type):
    base = decimal_value(base_amount)
    if base < 0:
        return base.quantize(decimal_value("0.01")), decimal_value(0), None
    rule = _find_matching_rule(airline, airline_type, base)
    percentage = decimal_value(rule.get("percentage")) if rule else decimal_value(0)
    discount = (base * percentage) / decimal_value(100)
    final_amount = max(decimal_value(0), base - discount).quantize(decimal_value("0.01"))
    return final_amount, percentage, rule


def calculate_coupon(booking):
    amount = money(booking.get("net_amount"))
    points = round(amount / 100, 2)
    return points, _find_matching_rule(
        booking.get("airline"),
        booking.get("fare_type"),
        booking.get("base_amount", amount),
    )


def _coupon_points(coupon, bookings=None):
    if coupon.get("points") is not None:
        return money(coupon.get("points"))
    if bookings is None:
        bookings = read("bookings")
    booking = next(
        (b for b in bookings if str(b.get("booking_id")) == str(coupon.get("booking_id"))),
        None,
    )
    return money(booking.get("net_amount")) / 100 if booking else 0.0


def _coupon_status_for_travel(coupon, bookings=None):
    if bookings is None:
        bookings = read("bookings")
    booking = next(
        (b for b in bookings if str(b.get("booking_id")) == str(coupon.get("booking_id"))),
        None,
    )
    if str((booking or {}).get("status", "")).strip().casefold() == "cancelled":
        return "EXPIRED"
    if coupon.get("status") in {"REDEEMED", "EXPIRED"}:
        return coupon["status"]
    if coupon.get("is_released") or coupon.get("status") == "AVAILABLE":
        return "AVAILABLE"
    travel_date = (booking or {}).get("travel_date") or coupon.get("travel_start_date") or coupon.get("unlock_date")
    if not travel_date:
        return "PENDING"
    try:
        return "AVAILABLE" if timezone.localdate() > date.fromisoformat(str(travel_date)[:10]) else "PENDING"
    except ValueError:
        return "PENDING"


def _resolve_booking(identifier):
    if not identifier:
        return None
    val = str(identifier).strip()
    booking = None
    if val.isdigit():
        booking = Booking.objects.select_related("client").filter(pk=int(val)).first()
    if not booking:
        booking = Booking.objects.select_related("client").filter(ticket_no=val).first()
    if not booking:
        booking = Booking.objects.select_related("client").filter(pnr=val).first()
    return booking


def auto_release_coupons():
    coupons = read("coupons")
    bookings = read("bookings")
    changed = False
    for c in coupons:
        status = _coupon_status_for_travel(c, bookings)
        points = _coupon_points(c, bookings)
        booking = next(
            (b for b in bookings if str(b.get("booking_id")) == str(c.get("booking_id"))),
            None,
        )
        if c.get("points") != points:
            c["points"] = points; changed = True
        if c.get("status") != status and (
            c.get("status") != "REDEEMED" or status == "EXPIRED"
        ):
            c["status"] = status; changed = True
        released = status == "AVAILABLE" or c.get("status") == "REDEEMED"
        if bool(c.get("is_released")) != released:
            c["is_released"] = released; changed = True
        if booking:
            for key, value in (("travel_start_date", booking.get("travel_date", "")), ("travel_end_date", booking.get("end_date", "")), ("passenger_name", booking.get("passenger_name", ""))):
                if c.get(key) != value:
                    c[key] = value; changed = True
    if changed:
        write("coupons", coupons)
    return coupons

def page_context(request, **kwargs):
    return {
        "current_user": request.session.get("user_name", "Super Admin"),
        "today": date.today().isoformat(),
        **kwargs,
    }


def login_view(request):
    if request.session.get("user_id"):
        return redirect("dashboard")

    if request.method == "POST":
        username = request.POST.get("username", "").strip()
        password = request.POST.get("password", "")
        users = read("users")

        user = next((u for u in users if u.get("username") == username), None)
        valid_password = False
        if user:
            stored_password = str(user.get("password", ""))
            if stored_password.startswith(("pbkdf2_", "argon2$", "bcrypt$")):
                valid_password = check_password(password, stored_password)
            else:
                # Supports one-time login for legacy plaintext records.
                valid_password = stored_password == password
                if valid_password:
                    user["password"] = make_password(password)
                    write("users", users)

        if user and valid_password:
            request.session["user_id"] = user["id"]
            request.session["user_name"] = user.get("name", username)
            request.session["role"] = user.get("role", "Admin")
            return redirect("dashboard")

        messages.error(request, "Invalid username or password.")

    return render(request, "login.html")


def logout_view(request):
    if request.method == "POST":
        request.session.flush()
        return redirect("login")
    return redirect("dashboard")


@admin_required
def dashboard(request):
    customers = read("customers")
    bookings = read("bookings")
    coupons = auto_release_coupons()
    ledger = read("ledger")

    available = sum(_coupon_points(c, bookings) for c in coupons if c.get("status") == "AVAILABLE")
    pending = sum(_coupon_points(c, bookings) for c in coupons if c.get("status") == "PENDING")
    total_coupon_points = available + pending
    earned = sum(_coupon_points(c, bookings) for c in coupons if c.get("status") in {"PENDING", "AVAILABLE", "REDEEMED"})
    redeemed = sum(abs(money(x.get("amount", 0))) for x in ledger if x.get("type") == "Coupon Redeemed")

    return render(request, "dashboard.html", page_context(
        request,
        available=available,
        pending=pending,
        earned=earned,
        redeemed=redeemed,
        total_coupon_points=total_coupon_points,
        booking_count=len(bookings),
        customer_count=len(customers),
        recent=ledger[:8],
    ))


@admin_required
def client_portal(request):
    customers = read("customers")
    client_query = request.GET.get("client_id", "").strip()
    selected_id = next((c["id"] for c in customers if c.get("id", "").casefold() == client_query.casefold()), "")
    customer = next((c for c in customers if c["id"] == selected_id), None)

    # Date range filter params
    from_date_str = request.GET.get("from_date", "").strip()
    to_date_str = request.GET.get("to_date", "").strip()
    try:
        from_date_obj = date.fromisoformat(from_date_str) if from_date_str else None
    except ValueError:
        from_date_obj = None
    try:
        to_date_obj = date.fromisoformat(to_date_str) if to_date_str else None
    except ValueError:
        to_date_obj = None
    date_filter_active = bool(from_date_obj or to_date_obj)

    all_bookings = read("bookings")
    for booking in all_bookings:
        if booking.get("booking_type") in {"Round Trip", "One Way"} and not booking.get("travel_type"):
            booking["travel_type"] = booking["booking_type"]
            booking["booking_type"] = "Web Booking"
        booking.setdefault("booking_type", "Web Booking")
        booking.setdefault("travel_type", "")

    # All bookings for this client (before date filter)
    bookings = [b for b in all_bookings if not selected_id or b.get("client_id") == selected_id]

    # Apply date range filter on bookings for date-filtered stats
    def _booking_in_range(b):
        td_raw = b.get("travel_date")
        if not td_raw:
            return False
        try:
            td = date.fromisoformat(str(td_raw)[:10])
        except ValueError:
            return False
        if from_date_obj and td < from_date_obj:
            return False
        if to_date_obj and td > to_date_obj:
            return False
        return True

    # Filtered bookings for date-range stats (only when a client is selected)
    filtered_bookings = [b for b in bookings if _booking_in_range(b)] if date_filter_active else bookings

    # Passenger keys from filtered bookings
    filtered_passenger_keys = {
        str(b.get("ticket_no") or b.get("passenger_name") or b.get("booking_id") or "").strip().casefold()
        for b in filtered_bookings
    }
    filtered_passenger_keys.discard("")

    # All passenger keys (unfiltered) for the overall count
    passenger_keys = {
        str(b.get("ticket_no") or b.get("passenger_name") or b.get("booking_id") or "").strip().casefold()
        for b in bookings
    }
    passenger_keys.discard("")

    all_coupons = auto_release_coupons()
    coupons = [c for c in all_coupons if not selected_id or c.get("customer_id") == selected_id]

    # For date-filtered coupon stats: only include coupons whose booking travel_date is in range
    if date_filter_active:
        filtered_booking_ids = {str(b.get("booking_id")) for b in filtered_bookings}
        filtered_coupons = [
            c for c in coupons if str(c.get("booking_id")) in filtered_booking_ids
        ]
    else:
        filtered_coupons = coupons

    available = sum(_coupon_points(c, all_bookings) for c in filtered_coupons if c.get("status") == "AVAILABLE")
    pending = sum(_coupon_points(c, all_bookings) for c in filtered_coupons if c.get("status") == "PENDING")
    total_coupon_points = available + pending
    earned = sum(_coupon_points(c, all_bookings) for c in coupons if c.get("status") in ["PENDING", "AVAILABLE", "REDEEMED"])
    customer_count = 1 if customer else len(customers)
    client_summaries = []
    for client in customers:
        client_bookings = [b for b in all_bookings if b.get("client_id") == client.get("id")]
        client_passenger_keys = {
            str(b.get("ticket_no") or b.get("passenger_name") or b.get("booking_id") or "").strip().casefold()
            for b in client_bookings
        }
        client_passenger_keys.discard("")
        # When date filter is active, compute filtered passenger count per client
        if date_filter_active:
            filtered_client_bookings = [b for b in client_bookings if _booking_in_range(b)]
            filtered_client_pax_keys = {
                str(b.get("ticket_no") or b.get("passenger_name") or b.get("booking_id") or "").strip().casefold()
                for b in filtered_client_bookings
            }
            filtered_client_pax_keys.discard("")
            client_summaries.append({
                **client,
                "passenger_count": len(filtered_client_pax_keys),
                "total_passenger_count": len(client_passenger_keys),
            })
        else:
            client_summaries.append({**client, "passenger_count": len(client_passenger_keys), "total_passenger_count": len(client_passenger_keys)})
    if client_query:
        client_summaries = [
            client for client in client_summaries
            if client_query.casefold() in str(client.get("id", "")).casefold()
        ]

    passenger_query = request.GET.get("passenger_name", "").strip()
    passenger_matches = _filter_passengers_by_name(bookings, passenger_query)
    selected_booking_ref = request.GET.get("selected_passenger", "").strip()
    close_modal = request.GET.get("close_modal", "").strip()
    if selected_booking_ref:
        selected_booking = next(
            (b for b in bookings if str(b.get("booking_id")) == selected_booking_ref), None
        )
    elif passenger_query and passenger_matches and not close_modal:
        selected_booking = passenger_matches[0]
        selected_booking_ref = str(selected_booking.get("booking_id", ""))
    else:
        selected_booking = None
    passenger_history = []
    passenger_points = 0
    if selected_booking:
        passenger_name = str(selected_booking.get("passenger_name") or "").strip()
        passenger_history = [
            dict(b) for b in bookings
            if passenger_name and str(b.get("passenger_name") or "").strip().casefold() == passenger_name.casefold()
        ] or [dict(selected_booking)]
        for trip in passenger_history:
            trip["history_end_date"] = trip.get("end_date") or trip.get("travel_date") or "-"
            trip["trip_status"] = (
                "INACTIVE" if trip.get("travel_date") and trip["travel_date"] < date.today().isoformat()
                else "ACTIVE"
            )
        passenger_coupons = [
            c for c in all_coupons
            if str(c.get("passenger_name") or "").strip().casefold() == passenger_name.casefold()
            or str(c.get("booking_id")) in {str(h.get("booking_id")) for h in passenger_history}
        ]
        passenger_available = sum(_coupon_points(c, all_bookings) for c in passenger_coupons if c.get("status") == "AVAILABLE")
        passenger_pending = sum(_coupon_points(c, all_bookings) for c in passenger_coupons if c.get("status") == "PENDING")
        passenger_points = passenger_available + passenger_pending

    return render(request, "client_portal.html", page_context(
        request,
        customers=customers,
        client_summaries=client_summaries,
        client_query=client_query,
        customer=customer,
        bookings=bookings,
        passenger_count=len(filtered_passenger_keys) if date_filter_active else len(passenger_keys),
        passenger_matches=passenger_matches,
        passenger_query=passenger_query,
        selected_booking_ref=selected_booking_ref,
        selected_booking=selected_booking,
        passenger_history=passenger_history,
        passenger_points=passenger_points,
        passenger_available=passenger_available if selected_booking else 0,
        passenger_pending=passenger_pending if selected_booking else 0,
        passenger_coupons=passenger_coupons if selected_booking else [],
        available=available,
        pending=pending,
        earned=earned,
        total_coupon_points=total_coupon_points,
        booking_count=len(bookings),
        customer_count=customer_count,
        from_date=from_date_str,
        to_date=to_date_str,
        date_filter_active=date_filter_active,
    ))


@admin_required
def customers(request):
    bookings = read("bookings")
    customer_rows = []

    for customer in read("customers"):
        client_id = customer.get("id")
        client_bookings = [b for b in bookings if b.get("client_id") == client_id]

        # Always show the customer, even when no booking exists yet.
        if not client_bookings:
            customer_rows.append({
                **customer,
                "booking_type": "-",
                "travel_type": "-",
                "travel_start": "-",
                "travel_end": "-",
                "booked_date": "-",
                "amount": 0,
            })
            continue

        for booking in client_bookings:
            booking_type = booking.get("booking_type") or "Web Booking"
            travel_type = booking.get("travel_type") or "-"
            if booking_type in {"Round Trip", "One Way"} and travel_type == "-":
                travel_type = booking_type
                booking_type = "Web Booking"
            customer_rows.append({
                **customer,
                "booking_type": booking_type,
                "travel_type": travel_type,
                "travel_start": booking.get("travel_date") or "-",
                "travel_end": booking.get("end_date") or booking.get("travel_date") or "-",
                "booked_date": booking.get("booked_date") or "-",
                "amount": money(booking.get("net_amount")),
            })

    return render(request, "customers.html", page_context(request, customers=customer_rows))


@admin_required
@require_POST
def add_customer(request):
    customers = read("customers")
    redirect_to = "bookings" if request.POST.get("return_to") == "bookings" else "customers"
    customer_id = request.POST.get("id", "").strip()
    name = request.POST.get("name", "").strip()
    email = request.POST.get("email", "").strip()
    phone = request.POST.get("phone", "").strip()

    if not all((customer_id, name, email, phone)):
        messages.error(request, "Client ID, name, email, and phone are required.")
        return redirect(redirect_to)

    if any(c["id"] == customer_id for c in customers):
        messages.error(request, "Customer ID already exists.")
        return redirect(redirect_to)

    customers.insert(0, {
        "id": customer_id,
        "name": name,
        "email": email,
        "phone": phone,
        "status": "ACTIVE"
    })
    write("customers", customers)
    messages.success(request, "Customer added successfully.")
    return redirect(redirect_to)


@admin_required
@require_POST
def edit_customer(request):
    customers_data = read("customers")
    cid = request.POST.get("id", "").strip()
    customer = next((c for c in customers_data if c.get("id") == cid), None)
    if not customer:
        messages.error(request, "Customer not found.")
        return redirect("customers")
    name = request.POST.get("name", "").strip()
    email = request.POST.get("email", "").strip()
    phone = request.POST.get("phone", "").strip()
    if not all((name, email, phone)):
        messages.error(request, "Name, email, and phone are required.")
        return redirect("customers")
    customer.update({
        "name": name,
        "email": email,
        "phone": phone,
        "status": request.POST.get("status", "ACTIVE"),
    })
    write("customers", customers_data)
    messages.success(request, "Customer updated successfully.")
    return redirect("customers")

@admin_required
@require_POST
def delete_customer(request):
    cid = request.POST.get("id", "").strip()
    customers_data = read("customers")
    if any(b.get("client_id") == cid for b in read("bookings")):
        messages.error(request, "Customer cannot be deleted because bookings exist for this client.")
        return redirect("customers")
    new_data = [c for c in customers_data if c.get("id") != cid]
    write("customers", new_data)
    messages.success(request, "Customer deleted.")
    return redirect("customers")

@admin_required
def bookings(request):
    q = request.GET.get("q", "").strip().lower()
    data = read("bookings")
    for booking in data:
        booking.setdefault("booking_type", "Web Booking")
        booking.setdefault("travel_type", "")
        booking.setdefault("airline", "")
        booking.setdefault("fare_type", "ANY CLASS")
        booking["status"] = "Cancelled" if (str(booking.get("status", "")).strip().lower() == "cancelled" or money(booking.get("net_amount", 0)) < 0) else "Confirmed"
    if q:
        searchable_fields = ("s_pnr", "ticket_no", "passenger_name", "airline", "sector", "status")
        data = [
            b for b in data
            if q in " ".join(str(b.get(field, "")) for field in searchable_fields).casefold()
        ]
    return render(request, "bookings.html", page_context(
        request, bookings=data, search=q, customers=read("customers"),
        airlines=AIRLINES, airline_types=AIRLINE_TYPES,
        booking_methods=BOOKING_METHODS, travel_types=TRAVEL_TYPES,
        booking_statuses=Booking.STATUS_CHOICES,
        rules=read("rules"), rules_json=json.dumps(read("rules")),
    ))


def _cancel_booking_and_revoke_coupon(booking):
    booking.status = "Cancelled"
    booking.save()

    coupon = Coupon.objects.select_for_update().filter(booking=booking).first()
    if coupon is None or (
        coupon.status == "EXPIRED"
        and decimal_value(coupon.amount) == 0
        and decimal_value(coupon.redeemed_amount) == 0
    ):
        return False

    earned_points = decimal_value(coupon.amount) + decimal_value(coupon.redeemed_amount)
    if earned_points > 0:
        txn_id = new_id("TXN-REV")
        Ledger.objects.create(
            id=txn_id,
            txn_id=txn_id,
            customer=coupon.customer,
            customer_name=coupon.customer_name,
            booking=booking,
            booking_ref=booking.pnr,
            coupon_code=coupon.coupon_code or coupon.id,
            type="Coupon Reversed",
            amount=-earned_points,
            status="REVERSED",
            date=timezone.localdate(),
        )

    coupon.amount = 0
    coupon.redeemed_amount = 0
    coupon.status = "EXPIRED"
    coupon.is_released = False
    coupon.save(update_fields=[
        "amount", "redeemed_amount", "status", "is_released", "updated_at",
    ])
    return True


@admin_required
@require_POST
def add_booking(request):
    client_id = request.POST.get("client_id", "").strip()
    client_record = Customer.objects.filter(id=client_id).first()
    ticket_no = request.POST.get("ticket_no", "").strip()

    required_fields = {
        "S PNR": request.POST.get("s_pnr", "").strip(),
        "Ticket No": ticket_no,
        "Client ID": client_id,
        "Passenger Name": request.POST.get("passenger_name", "").strip(),
        "Sector": request.POST.get("sector", "").strip(),
        "Booking Type": request.POST.get("booking_type", "").strip(),
        "Travel Type": request.POST.get("travel_type", "").strip(),
        "Airline Name": request.POST.get("airline", "").strip(),
        "Airline Type": request.POST.get("fare_type", "").strip(),
        "Airline PNR": request.POST.get("airline_pnr", "").strip(),
        "Net Amount": request.POST.get("net_amount", "").strip(),
        "Travel Start Date": request.POST.get("travel_date", "").strip(),
        "Travel End Date": request.POST.get("end_date", "").strip(),
        "Booking Date": request.POST.get("booked_date", "").strip(),
    }
    missing = [label for label, value in required_fields.items() if not value]
    if missing or client_record is None:
        messages.error(request, "Please fill all required booking fields: " + ", ".join(missing or ["valid Client ID"]) + ".")
        return redirect("bookings")

    try:
        raw_net = str(required_fields["Net Amount"]).replace(",", "").replace("₹", "").strip()
        parsed_net = Decimal(raw_net)
        if not parsed_net.is_finite():
            raise InvalidOperation
    except (InvalidOperation, TypeError, ValueError):
        messages.error(request, "Net Amount must be a valid number.")
        return redirect("bookings")

    # If Net Amount is negative, status is automatically Cancelled; if positive, Confirmed (or user-selected)
    if parsed_net < 0:
        status_val = "Cancelled"
    else:
        status_val = request.POST.get("status", "Confirmed").strip() or "Confirmed"
        if status_val not in dict(Booking.STATUS_CHOICES):
            status_val = "Confirmed"

    if Booking.objects.filter(ticket_no=ticket_no).exists():
        messages.error(request, "This Ticket No already exists.")
        return redirect("bookings")

    final_net, discount_pct, matched_rule = calculate_discounted_net(
        parsed_net, required_fields["Airline Name"], required_fields["Airline Type"]
    )
    Booking.objects.create(
        pnr=required_fields["S PNR"],
        ticket_no=ticket_no,
        client=client_record,
        passenger_name=required_fields["Passenger Name"],
        sector=required_fields["Sector"],
        booking_type=required_fields["Booking Type"],
        travel_type=required_fields["Travel Type"],
        airline=required_fields["Airline Name"],
        fare_type=required_fields["Airline Type"],
        airline_pnr=required_fields["Airline PNR"],
        net_amount=decimal_value(final_net),
        base_amount=decimal_value(parsed_net),
        discount_percentage=decimal_value(discount_pct),
        travel_date=date_value(required_fields["Travel Start Date"]),
        end_date=date_value(required_fields["Travel End Date"]),
        booked_date=date_value(required_fields["Booking Date"]),
        status=status_val,
        is_auto=False,
        is_manual=True,
    )
    messages.success(request, f"Booking added successfully (Status: {status_val}). Final Net Amount: ₹{money(final_net):,.2f}" + (f" ({money(discount_pct):g}% discount)" if matched_rule else ""))
    return redirect("bookings")


@admin_required
@require_POST
def edit_booking(request):
    booking_id = request.POST.get("booking_id", "").strip()
    booking = _resolve_booking(booking_id)
    if booking is None:
        messages.error(request, "Booking not found.")
        return redirect("bookings")
    client_id = request.POST.get("client_id", "").strip()
    client_record = Customer.objects.filter(id=client_id).first()
    ticket_no = request.POST.get("ticket_no", "").strip()
    values = {
        "ticket_no": ticket_no,
        "passenger_name": request.POST.get("passenger_name", "").strip(),
        "sector": request.POST.get("sector", "").strip(),
        "booking_type": request.POST.get("booking_type", "").strip(),
        "travel_type": request.POST.get("travel_type", "").strip(),
        "airline": request.POST.get("airline", "").strip(),
        "fare_type": request.POST.get("fare_type", "").strip(),
        "airline_pnr": request.POST.get("airline_pnr", "").strip(),
        "net_amount": request.POST.get("net_amount", "").strip(),
        "travel_date": request.POST.get("travel_date", "").strip(),
        "end_date": request.POST.get("end_date", "").strip(),
        "booked_date": request.POST.get("booked_date", "").strip(),
    }
    missing = [k for k,v in values.items() if not v]
    if missing or client_record is None:
        messages.error(request, "All booking fields are compulsory. Please fill every field.")
        return redirect("bookings")
    try:
        raw_net = str(values["net_amount"]).replace(",", "").replace("₹", "").strip()
        parsed_net = Decimal(raw_net)
        if not parsed_net.is_finite():
            raise InvalidOperation
    except (InvalidOperation, TypeError, ValueError):
        messages.error(request, "Net Amount must be a valid number.")
        return redirect("bookings")

    if parsed_net < 0:
        status_val = "Cancelled"
    else:
        status_val = request.POST.get("status", "Confirmed").strip() or "Confirmed"
        if status_val not in dict(Booking.STATUS_CHOICES):
            status_val = "Confirmed"

    if Booking.objects.filter(ticket_no=ticket_no).exclude(pk=booking.pk).exists():
        messages.error(request, "This Ticket No already exists.")
        return redirect("bookings")
    final_net, discount_pct, matched_rule = calculate_discounted_net(parsed_net, values["airline"], values["fare_type"])
    booking.client = client_record
    booking.ticket_no = ticket_no
    booking.passenger_name = values["passenger_name"]
    booking.sector = values["sector"]
    booking.booking_type = values["booking_type"]
    booking.travel_type = values["travel_type"]
    booking.airline = values["airline"]
    booking.fare_type = values["fare_type"]
    booking.airline_pnr = values["airline_pnr"]
    booking.net_amount = decimal_value(final_net)
    booking.base_amount = decimal_value(parsed_net)
    booking.discount_percentage = decimal_value(discount_pct)
    booking.travel_date = date_value(values["travel_date"])
    booking.end_date = date_value(values["end_date"])
    booking.booked_date = date_value(values["booked_date"])
    if status_val == "Cancelled":
        with transaction.atomic():
            _cancel_booking_and_revoke_coupon(booking)
    else:
        booking.status = status_val
        booking.save()
    messages.success(request, f"Booking {booking.pnr} updated successfully (Status: {status_val}). Final Net Amount: ₹{money(final_net):,.2f}" + (f" ({money(discount_pct):g}% discount)" if matched_rule else ""))
    return redirect("bookings")


@admin_required
@require_POST
def delete_booking(request):
    booking_id = request.POST.get("booking_id", "").strip()
    if not booking_id:
        messages.error(request, "Booking ID is required to cancel a booking.")
        return redirect("bookings")
    booking = _resolve_booking(booking_id)
    if not booking:
        messages.error(request, "Booking not found.")
        return redirect("bookings")
    with transaction.atomic():
        _cancel_booking_and_revoke_coupon(booking)
    messages.success(request, f"Booking {booking.pnr} / {booking.ticket_no} cancelled.")
    return redirect("bookings")

@admin_required
def coupons(request):
    bookings_data = read("bookings")
    coupon_data = auto_release_coupons()
    available_points = sum(_coupon_points(c, bookings_data) for c in coupon_data if c.get("status") == "AVAILABLE")
    pending_points = sum(_coupon_points(c, bookings_data) for c in coupon_data if c.get("status") == "PENDING")
    # Data used by the popup auto-fill.
    passenger_records = []
    for b in bookings_data:
        passenger_records.append({
            "booking_id": str(b.get("booking_id", "")),
            "passenger_name": b.get("passenger_name", ""),
            "client_id": b.get("client_id", ""), "client_name": b.get("client", ""),
            "s_pnr": b.get("s_pnr", ""), "ticket_no": b.get("ticket_no", ""), "net_amount": money(b.get("net_amount")),
            "sector": b.get("sector", ""), "airline": b.get("airline", ""),
            "fare_type": b.get("fare_type", ""), "airline_pnr": b.get("airline_pnr", ""),
            "travel_date": b.get("travel_date", ""), "end_date": b.get("end_date", ""),
            "booked_date": b.get("booked_date", ""),
        })
    coupon_records_for_ui = [
        {
            "booking_id": str(coupon.get("booking_id", "")),
            "passenger_name": coupon.get("passenger_name", ""),
            "points": coupon.get("points", 0),
            "status": coupon.get("status", ""),
        }
        for coupon in coupon_data
    ]
    return render(request, "coupons.html", page_context(
        request, coupons=coupon_data, customers=read("customers"), bookings=bookings_data,
        passenger_records=passenger_records, passenger_records_json=json.dumps(passenger_records), coupon_records_json=json.dumps(coupon_records_for_ui), available_points=available_points, pending_points=pending_points,
        total_coupon_points=available_points + pending_points,
    ))


@admin_required
@require_POST
def earn_coupon(request):
    booking_id = request.POST.get("booking_id", "").strip()
    if not booking_id:
        messages.error(request, "Select a passenger booking.")
        return redirect("coupons")
    booking = _resolve_booking(booking_id)
    if not booking:
        messages.error(request, "Passenger booking not found.")
        return redirect("coupons")
    if booking.status == "Cancelled":
        messages.error(request, "A coupon cannot be earned for a cancelled booking.")
        return redirect("coupons")
    if Coupon.objects.filter(booking=booking).exists():
        existing = Coupon.objects.filter(booking=booking).first()
        messages.info(request, f"A coupon already exists for {booking.pnr} ({existing.status}).")
        return redirect("coupons")
    points = (decimal_value(booking.net_amount) / decimal_value(100)).quantize(
        decimal_value("0.01")
    )
    if points <= 0:
        messages.error(request, "Booking Net Amount must be greater than ₹0.")
        return redirect("coupons")
    available_now = bool(booking.travel_date and timezone.localdate() > booking.travel_date)
    status = "AVAILABLE" if available_now else "PENDING"
    coupon_id = new_id("CPN")
    coupon_code = f"CPN-{coupon_id.split('-', 1)[-1]}"
    redemption_date = timezone.localdate()
    with transaction.atomic():
        Coupon.objects.create(id=coupon_id, coupon_code=coupon_code, customer=booking.client, booking=booking, booking_ref=booking.pnr,
            customer_name=booking.client.name, passenger_name=booking.passenger_name, travel_date=booking.travel_date, amount=points,
            status=status, is_released=available_now, unlock_date=booking.travel_date, available_date=redemption_date if available_now else None, redeemed_amount=0)
        txn_id = new_id("TXN-EARN")
        Ledger.objects.create(id=txn_id, txn_id=txn_id, customer=booking.client, customer_name=booking.client.name, booking=booking,
            booking_ref=booking.pnr, coupon_code=coupon_code, type="Coupon Earned", amount=points, status=status, date=redemption_date)
    messages.success(request, f"Earn Coupon created: {money(points):,.2f} points ({status}). Coupon Amount when available: ₹{money(points/10):,.2f}.")
    return redirect("coupons")


@admin_required
@require_POST
def release_coupon(request):
    booking_id = request.POST.get("booking_id", "").strip()
    booking = _resolve_booking(booking_id)
    if not booking:
        messages.error(request, "Passenger booking not found.")
        return redirect("coupons")
    if booking.status == "Cancelled":
        messages.error(request, "A cancelled booking's coupon cannot be released.")
        return redirect("coupons")
    coupon = Coupon.objects.filter(booking=booking).first()
    if not coupon:
        messages.warning(request, "No coupon found. Earn the coupon first.")
        return redirect("coupons")
    if coupon.status == "REDEEMED":
        messages.warning(request, "This coupon has already been fully redeemed.")
        return redirect("coupons")
    coupon.status = "AVAILABLE"
    coupon.is_released = True
    coupon.available_date = timezone.localdate()
    coupon.save(update_fields=["status", "is_released", "available_date", "updated_at"])
    messages.success(request, f"Coupon for {booking.pnr} ({booking.ticket_no}) is now AVAILABLE. Coupon Amount: ₹{money(coupon.amount/10):,.2f}.")
    return redirect("coupons")


@admin_required
@require_POST
def redeem_coupon(request):
    booking_id = request.POST.get("booking_id", "").strip()
    if not booking_id:
        messages.error(request, "Select a passenger booking.")
        return redirect("coupons")
    booking = _resolve_booking(booking_id)
    if not booking:
        messages.error(request, "Passenger booking not found.")
        return redirect("coupons")
    if booking.status == "Cancelled":
        messages.error(request, "A coupon cannot be redeemed for a cancelled booking.")
        return redirect("coupons")
    customer = booking.client
    available = list(Coupon.objects.select_related("booking", "customer").filter(customer=customer, status="AVAILABLE", booking=booking).order_by("-created_at"))
    available = [c for c in available if decimal_value(c.amount) > 0][:1]
    if not available:
        messages.error(request, "Coupon is not AVAILABLE yet. It becomes available only on/after Travel Start Date.")
        return redirect("coupons")
    total_points = sum((decimal_value(c.amount) for c in available), decimal_value(0))
    coupon_amount = (total_points / decimal_value(10)).quantize(decimal_value("0.01"))
    if coupon_amount <= 0:
        messages.error(request, "Coupon Amount is ₹0.00.")
        return redirect("coupons")
    with transaction.atomic():
        for coupon in available:
            used_points = decimal_value(coupon.amount)
            coupon.redeemed_amount = decimal_value(coupon.redeemed_amount) + used_points
            coupon.amount = decimal_value(0)
            coupon.status = "REDEEMED"
            coupon.is_released = True
            coupon.save(update_fields=["amount", "redeemed_amount", "status", "is_released", "updated_at"])
        old_net = decimal_value(booking.net_amount)
        booking.net_amount = max(decimal_value(0), old_net - coupon_amount)
        booking.save(update_fields=["net_amount", "updated_at"])
        redemption_id = new_id("RDM")
        codes = ", ".join(c.coupon_code or c.id for c in available)
        redemption = Redemption.objects.create(id=redemption_id, customer=customer, customer_name=customer.name, booking_id=str(booking.pk), booking_ref=booking.pnr,
            coupon_code=codes, amount=coupon_amount, redeemed_amount=coupon_amount, status="COMPLETED", redemption_type="Coupon Redemption", time=now().split(" ")[1][:5])
        for coupon in available:
            RedemptionAllocation.objects.create(redemption=redemption, coupon_code=coupon.coupon_code or coupon.id, amount=(decimal_value(coupon.redeemed_amount)))
        Ledger.objects.create(id=new_id("TXN-RED"), txn_id=redemption_id, customer=customer, customer_name=customer.name, booking=booking, booking_ref=booking.pnr,
            coupon_code=codes, type="Coupon Redeemed", amount=-coupon_amount, status="SUCCESS", date=timezone.localdate())
    messages.success(request, f"Coupon redeemed: ₹{money(coupon_amount):,.2f}. Booking Net Amount updated to ₹{money(booking.net_amount):,.2f}.")
    return redirect("coupons")


@admin_required
@require_POST
def reverse_coupon(request):
    booking_id = request.POST.get("booking_id", "").strip()
    if not booking_id:
        messages.error(request, "Select a passenger booking.")
        return redirect("coupons")
    booking = _resolve_booking(booking_id)
    if not booking:
        messages.error(request, "Passenger booking not found.")
        return redirect("coupons")
    if booking.status == "Cancelled":
        messages.error(request, "A cancelled booking's coupon cannot be restored.")
        return redirect("coupons")
    redemption = Redemption.objects.filter(booking_id=str(booking.pk), status__in=["COMPLETED", "SUCCESS"]).order_by("-date").first()
    if not redemption:
        messages.error(request, "No completed redemption was found for this passenger.")
        return redirect("coupons")
    restored_amount = decimal_value(redemption.redeemed_amount or redemption.amount)
    restored_points = (restored_amount * decimal_value(10)).quantize(decimal_value("0.01"))
    with transaction.atomic():
        coupon = Coupon.objects.filter(booking=booking).first()
        if not coupon:
            messages.error(request, "Coupon record not found.")
            return redirect("coupons")
        coupon.amount = decimal_value(coupon.amount) + restored_points
        coupon.redeemed_amount = max(decimal_value(0), decimal_value(coupon.redeemed_amount) - restored_points)
        coupon.status = "AVAILABLE" if booking.travel_date and timezone.localdate() > booking.travel_date else "PENDING"
        coupon.is_released = coupon.status == "AVAILABLE"
        coupon.save(update_fields=["amount", "redeemed_amount", "status", "is_released", "updated_at"])
        booking.net_amount = decimal_value(booking.net_amount) + restored_amount
        booking.save(update_fields=["net_amount", "updated_at"])
        redemption.status = "REVERSED"; redemption.reversed_at = timezone.now(); redemption.reversed_amount = restored_amount
        redemption.save(update_fields=["status", "reversed_at", "reversed_amount"])
        Ledger.objects.create(id=new_id("TXN-REV"), txn_id=new_id("TXN-REV"), customer=redemption.customer, customer_name=redemption.customer_name, booking=booking,
            booking_ref=booking.pnr, coupon_code=redemption.coupon_code, type="Coupon Reversed", amount=restored_amount, status="REVERSED", date=timezone.localdate())
    messages.success(request, f"Coupon reversed: ₹{money(restored_amount):,.2f} added back to Net Amount and {money(restored_points):,.2f} points restored.")
    return redirect("coupons")

@admin_required
def redemptions(request):
    raw_redemptions = read("redemptions")
    search = request.GET.get("q", "").strip()
    coupon_code_filter = request.GET.get("coupon_code", "").strip()
    status_filter = request.GET.get("status", "").strip()
    from_date = request.GET.get("from_date", "").strip()
    to_date = request.GET.get("to_date", "").strip()

    available_coupon_codes = sorted({
        str(r.get("coupon_code", "")).strip()
        for r in raw_redemptions if r.get("coupon_code")
    })
    available_statuses = sorted({
        str(r.get("status", "")).strip()
        for r in raw_redemptions if r.get("status")
    })

    filtered = []
    for r in raw_redemptions:
        customer = str(r.get("customer_name") or r.get("customer") or r.get("customer_id") or "").strip()
        booking = str(r.get("booking_id") or r.get("booking_ref") or "").strip()
        code = str(r.get("coupon_code") or "").strip()
        rid = str(r.get("id") or "").strip()
        status = str(r.get("status") or "").strip()
        item_date = str(r.get("date") or "").strip()
        if " " in item_date:
            item_date, embedded_time = item_date.split(" ", 1)
        else:
            embedded_time = ""
        time_val = str(r.get("time") or embedded_time).strip()

        haystack = f"{rid} {customer} {booking} {code} {status}".casefold()
        if search and search.casefold() not in haystack:
            continue
        if coupon_code_filter and code.casefold() != coupon_code_filter.casefold():
            continue
        if status_filter and status.casefold() != status_filter.casefold():
            continue
        if from_date and item_date and item_date < from_date:
            continue
        if to_date and item_date and item_date > to_date:
            continue

        amount = money(r.get("redeemed_amount", r.get("amount", r.get("discount_amount", 0))))
        status_slug = status.casefold().replace(" ", "-")

        filtered.append({
            **r,
            "id": rid,
            "customer": customer or "-",
            "booking_id": booking or "-",
            "coupon_code": code or "-",
            "redeemed_amount": amount,
            "formatted_redeemed": f"₹{amount:,.2f}",
            "status": status or "-",
            "status_slug": status_slug,
            "redemption_type": r.get("redemption_type") or "Coupon Redemption",
            "date": item_date or "-",
            "time": time_val or "-",
        })

    filtered.sort(key=lambda row: f"{row.get('date','')} {row.get('time','')}", reverse=True)
    page_obj = Paginator(filtered, 10).get_page(request.GET.get("page"))
    total_count = len(filtered)

    return render(request, "redemptions.html", page_context(
        request,
        redemptions=page_obj,
        page_obj=page_obj,
        total_count=total_count,
        start_index=page_obj.start_index() if total_count else 0,
        end_index=page_obj.end_index() if total_count else 0,
        search=search,
        coupon_code_filter=coupon_code_filter,
        status_filter=status_filter,
        from_date=from_date,
        to_date=to_date,
        available_coupon_codes=available_coupon_codes,
        available_statuses=available_statuses,
        customers=read("customers"),
        coupons=read("coupons"),
    ))


@admin_required
@require_POST
def add_redemption(request):
    customer = request.POST.get("customer", "").strip()
    booking_id = request.POST.get("booking_id", "").strip()
    coupon_code = request.POST.get("coupon_code", "").strip()
    redeemed_amount = money(request.POST.get("redeemed_amount", 0))
    status = request.POST.get("status", "Completed").strip()
    redemption_type = request.POST.get("redemption_type", "Manual").strip()
    date_val = request.POST.get("date", "").strip()
    time_val = request.POST.get("time", "").strip()

    if not customer or not booking_id or redeemed_amount <= 0:
        messages.error(request, "Customer name, Booking ID, and a valid Redeemed Amount (> 0) are required.")
        return redirect("redemptions")

    now_str = now()
    if not date_val:
        date_val = now_str.split(" ")[0]
    if not time_val:
        time_val = now_str.split(" ")[1][:5] if " " in now_str else "00:00"

    redemptions_data = read("redemptions")
    existing_nums = []
    for r in redemptions_data:
        rid = str(r.get("id", ""))
        if rid.startswith("RDM") and rid[3:].isdigit():
            existing_nums.append(int(rid[3:]))
    next_num = max(existing_nums, default=0) + 1
    rid = f"RDM{next_num:03d}"

    redemptions_data.insert(0, {
        "id": rid,
        "customer": customer,
        "customer_name": customer,
        "booking_id": booking_id,
        "booking_ref": booking_id,
        "coupon_code": coupon_code or "-",
        "redeemed_amount": redeemed_amount,
        "status": status or "Completed",
        "redemption_type": redemption_type or "Manual",
        "date": date_val,
        "time": time_val,
    })
    write("redemptions", redemptions_data)
    messages.success(request, f"Redemption record {rid} added successfully.")
    return redirect("redemptions")


@admin_required
@require_POST
def delete_redemption(request):
    rid = request.POST.get("id", "").strip()
    redemptions_data = read("redemptions")
    record = next((r for r in redemptions_data if str(r.get("id")) == rid), None)
    if not record:
        messages.error(request, "Redemption record not found.")
        return redirect("redemptions")

    if str(record.get("redemption_type", "")).casefold() != "manual":
        messages.error(request, "Automatic coupon redemption records cannot be deleted. Use Reverse Coupon instead.")
        return redirect("redemptions")

    write("redemptions", [r for r in redemptions_data if str(r.get("id")) != rid])
    messages.success(request, f"Manual redemption record {rid} deleted.")
    return redirect("redemptions")


@admin_required
@require_POST
def clear_all_redemptions(request):
    redemptions_data = read("redemptions")
    manual = [r for r in redemptions_data if str(r.get("redemption_type", "")).casefold() == "manual"]
    automatic = [r for r in redemptions_data if str(r.get("redemption_type", "")).casefold() != "manual"]
    write("redemptions", automatic)
    messages.success(request, f"Cleared {len(manual)} manual redemption record(s). Automatic records were preserved.")
    return redirect("redemptions")


@admin_required
def ledger(request):
    """Ledger = coupon/customer transaction history.
    Shows: Customer, Booking Ref, Action (Coupon Earned / Coupon Redeemed),
    Coupon Amount, Coupon Code, Status.
    """
    ledger_entries = read("ledger")

    transactions = []
    for entry in ledger_entries:
        amount = money(entry.get("amount", 0))
        transactions.append({
            "txn_id": entry.get("txn_id", "-"),
            "date": entry.get("date") or entry.get("created_at") or "-",
            "customer_id": entry.get("customer_id", "-"),
            "customer_name": entry.get("customer_name", entry.get("customer_id", "-")),
            "booking_ref": entry.get("booking_ref", "-"),
            "booking_status": entry.get("booking_status", "-"),
            "ticket_no": entry.get("ticket_no", "-"),
            "type": entry.get("type", "Transaction"),
            "coupon_code": entry.get("coupon_code", "-"),
            "amount": amount,
            "status": entry.get("status", "-"),
        })

    transactions.sort(key=lambda row: str(row["date"]), reverse=True)

    # Filters
    search = request.GET.get("q", "").strip()
    transaction_type = request.GET.get("transaction_type", "").strip()
    from_date = request.GET.get("from_date", "").strip()
    to_date = request.GET.get("to_date", "").strip()

    filtered = transactions
    if search:
        query = search.casefold()
        filtered = [
            row for row in filtered
            if query in " ".join(str(row.get(key, "")) for key in (
                "txn_id", "customer_id", "customer_name", "booking_ref", "booking_status", "ticket_no", "type", "coupon_code"
            )).casefold()
        ]
    if transaction_type:
        filtered = [row for row in filtered if row["type"] == transaction_type]
    if from_date:
        filtered = [row for row in filtered if str(row["date"])[:10] >= from_date]
    if to_date:
        filtered = [row for row in filtered if str(row["date"])[:10] <= to_date]

    # Summary stats
    total_earned = sum(money(e.get("amount", 0)) for e in ledger_entries if e.get("type") == "Coupon Earned")
    total_redeemed = sum(abs(money(e.get("amount", 0))) for e in ledger_entries if e.get("type") == "Coupon Redeemed")
    total_reversed = sum(money(e.get("amount", 0)) for e in ledger_entries if e.get("type") == "Coupon Reversed")
    total_available = total_earned - total_redeemed + total_reversed
    total_transactions = len(ledger_entries)

    transaction_types = sorted({row["type"] for row in transactions if row["type"]})
    return render(request, "ledger.html", page_context(
        request,
        ledger=filtered,
        search=search,
        transaction_type=transaction_type,
        from_date=from_date,
        to_date=to_date,
        transaction_types=transaction_types,
        total_count=len(filtered),
        total_earned=total_earned,
        total_redeemed=total_redeemed,
        total_available=total_available,
        total_transactions=total_transactions,
    ))


def _normalise_excel_header(value):
    return "".join(character for character in str(value or "").casefold() if character.isalnum())


def _canonical_excel_headers(headers):
    aliases = {
        "spnr": "S PNR",
        "pnr": "S PNR",
        "bookingpnr": "S PNR",
        "ticketno": "Ticket No",
        "ticketnumber": "Ticket No",
        "ticket": "Ticket No",
        "clientid": "Client ID",
        "customerid": "Client ID",
        "passengername": "Passenger Name",
        "name": "Passenger Name",
        "sector": "Sector",
        "bookingtype": "Booking Type",
        "traveltype": "Travel Type",
        "airlinename": "Airline Name",
        "airline": "Airline Name",
        "airlinetype": "Airline Type",
        "faretype": "Airline Type",
        "airlinepnr": "Airline PNR",
        "netamount": "Net Amount",
        "amount": "Net Amount",
        "travelstartdate": "Travel Start Date",
        "traveldate": "Travel Start Date",
        "travelenddate": "Travel End Date",
        "enddate": "Travel End Date",
        "bookingdate": "Booking Date",
        "bookeddate": "Booking Date",
        "bookingstatus": "Status",
        "status": "Status",
    }
    return [
        aliases.get(_normalise_excel_header(header), str(header or "").strip())
        for header in headers
    ]


def _canonical_booking_status(value):
    if value is None:
        return None
    status = str(value).strip().casefold()
    if not status:
        return None
    return {
        "confirmed": "Confirmed",
        "cancelled": "Cancelled",
        "rescheduled": "Rescheduled",
    }.get(status)


def _add_excel_upload_failure(request, details=None):
    messages.error(request, "Something Went Wrong")
    if details:
        messages.warning(request, details)


@admin_required
def excel_upload(request):
    if request.method == "POST":
        action = request.POST.get("action", "").strip().lower()
        is_scan = (action == "scan") or (request.headers.get("x-requested-with") == "XMLHttpRequest" and action != "confirm")

        upload = request.FILES.get("excel_file")
        if not upload:
            if is_scan:
                return JsonResponse({"success": False, "error": "Choose an .xlsx workbook and try again."}, status=400)
            _add_excel_upload_failure(request, "Choose an .xlsx workbook and try again.")
            return redirect("excel_upload")

        workbook = None
        try:
            from openpyxl import load_workbook
            workbook = load_workbook(upload, read_only=True, data_only=True)
            ws = workbook.active
            raw_headers = [str(c.value).strip() if c.value is not None else "" for c in ws[1]]
            headers = _canonical_excel_headers(raw_headers)

            required_headers = [
                "S PNR",
                "Client ID",
                "Ticket No",
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
                "Status",
            ]
            missing = set(required_headers) - set(headers)
            if missing:
                err_msg = "Missing required Excel columns: " + ", ".join(sorted(missing)) + "."
                if is_scan:
                    return JsonResponse({"success": False, "error": err_msg}, status=400)
                _add_excel_upload_failure(request, err_msg)
                return redirect("excel_upload")

            existing_ticket_nos = {
                str(ticket_no).casefold()
                for ticket_no in Booking.objects.exclude(ticket_no__isnull=True).values_list("ticket_no", flat=True)
            }
            imported_ticket_nos = set()
            rows_to_import = []
            row_errors = []
            invalid_row_numbers = set()
            duplicate_skipped = 0

            for row_number, values in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
                row = dict(zip(headers, values))
                if not any(value is not None and str(value).strip() for value in values):
                    continue

                spnr = str(row.get("S PNR") or "").strip()

                try:
                    raw_amount = str(row.get("Net Amount") or "").strip().replace(",", "").replace("₹", "")
                    base_amount = Decimal(raw_amount)
                    if not base_amount.is_finite():
                        raise InvalidOperation
                except (InvalidOperation, TypeError, ValueError):
                    row_errors.append(f"Row {row_number}: Net Amount must be a valid number")
                    invalid_row_numbers.add(row_number)
                    continue

                missing_values = [
                    header for header in required_headers
                    if (row.get(header) is None or not str(row.get(header)).strip())
                    and not (header == "Status" and base_amount < 0)
                ]
                if missing_values:
                    row_errors.append(f"Row {row_number}: missing " + ", ".join(missing_values))
                    invalid_row_numbers.add(row_number)
                    continue

                parsed_dates = {}
                for header, field_name in (
                    ("Travel Start Date", "travel_date"),
                    ("Travel End Date", "end_date"),
                    ("Booking Date", "booked_date"),
                ):
                    parsed_date = date_value(row[header])
                    if isinstance(parsed_date, datetime):
                        parsed_date = parsed_date.date()
                    if parsed_date is None:
                        row_errors.append(f"Row {row_number}: {header} must be a valid date")
                        invalid_row_numbers.add(row_number)
                    else:
                        parsed_dates[field_name] = parsed_date

                if len(parsed_dates) != 3:
                    continue
                if not spnr:
                    row_errors.append(f"Row {row_number}: S PNR is required.")
                    invalid_row_numbers.add(row_number)
                    continue

                # Auto-status:
                # If Net Amount < 0 -> automatically "Cancelled"
                # If Net Amount >= 0 -> "Confirmed" or valid status from Excel
                if base_amount < 0:
                    booking_status = "Cancelled"
                else:
                    raw_status = row.get("Status")
                    if raw_status is not None and str(raw_status).strip():
                        booking_status = _canonical_booking_status(raw_status)
                        if booking_status is None:
                            row_errors.append(
                                f"Row {row_number}: Status must be Confirmed or Cancelled."
                            )
                            invalid_row_numbers.add(row_number)
                            continue
                    else:
                        booking_status = "Confirmed"

                ticket_no = str(row["Ticket No"]).strip()
                ticket_no_key = ticket_no.casefold()
                if ticket_no_key in imported_ticket_nos:
                    duplicate_skipped += 1
                    continue

                imported_ticket_nos.add(ticket_no_key)
                rows_to_import.append({
                    "s_pnr": spnr,
                    "ticket_no": ticket_no,
                    "is_update": ticket_no_key in existing_ticket_nos,
                    "client_id": str(row["Client ID"]).strip(),
                    "client": str(row.get("Client") or row["Client ID"]).strip(),
                    "passenger_name": str(row["Passenger Name"]).strip(),
                    "sector": str(row["Sector"]).strip(),
                    "booking_type": str(row["Booking Type"]).strip(),
                    "travel_type": str(row["Travel Type"]).strip(),
                    "airline": str(row["Airline Name"]).strip(),
                    "fare_type": str(row["Airline Type"]).strip(),
                    "airline_pnr": str(row["Airline PNR"]).strip(),
                    "base_amount": base_amount,
                    "status": booking_status or "Confirmed",
                    **parsed_dates,
                })

            if not rows_to_import or invalid_row_numbers:
                details = (
                    "; ".join(row_errors[:5])
                    if row_errors
                    else "No booking rows were found in the worksheet."
                )
                if len(row_errors) > 5:
                    details += f"; and {len(row_errors) - 5} more row error(s)."
                if is_scan:
                    return JsonResponse({"success": False, "error": details}, status=400)
                _add_excel_upload_failure(request, details)
                return redirect("excel_upload")

            if is_scan:
                total_passengers = len(rows_to_import)
                total_confirmed = sum(1 for r in rows_to_import if r["status"] == "Confirmed")
                total_cancelled = sum(1 for r in rows_to_import if r["status"] == "Cancelled")
                total_rescheduled = sum(1 for r in rows_to_import if r["status"] == "Rescheduled")
                total_net_amount = sum((r["base_amount"] for r in rows_to_import), Decimal("0"))
                return JsonResponse({
                    "success": True,
                    "total_passengers": total_passengers,
                    "total_confirmed": total_confirmed,
                    "total_cancelled": total_cancelled,
                    "total_rescheduled": total_rescheduled,
                    "total_net_amount": f"₹ {total_net_amount:,.2f}",
                    "duplicate_skipped": duplicate_skipped,
                })

            with transaction.atomic():
                customers_by_id = Customer.objects.in_bulk({row["client_id"] for row in rows_to_import})
                existing_bookings = {
                    booking.ticket_no: booking
                    for booking in Booking.objects.select_for_update().filter(
                        ticket_no__in=[row["ticket_no"] for row in rows_to_import if row["is_update"]]
                    )
                }
                new_bookings = []
                updated = 0
                for row in rows_to_import:
                    customer = customers_by_id.get(row["client_id"])
                    if customer is None:
                        customer = get_or_create_customer({
                            "client_id": row["client_id"],
                            "client": row["client"],
                        })
                        customers_by_id[row["client_id"]] = customer

                    final_amount, discount_percentage, _ = calculate_discounted_net(
                        row["base_amount"], row["airline"], row["fare_type"]
                    )
                    booking = existing_bookings.get(row["ticket_no"])
                    if booking is None:
                        new_bookings.append(Booking(
                            pnr=row["s_pnr"],
                            ticket_no=row["ticket_no"],
                            client=customer,
                            passenger_name=row["passenger_name"],
                            sector=row["sector"],
                            travel_date=row["travel_date"],
                            end_date=row["end_date"],
                            booked_date=row["booked_date"],
                            net_amount=final_amount,
                            base_amount=row["base_amount"],
                            discount_percentage=discount_percentage,
                            airline=row["airline"],
                            fare_type=row["fare_type"],
                            airline_pnr=row["airline_pnr"],
                            booking_type=row["booking_type"],
                            travel_type=row["travel_type"],
                            status=row["status"] or "Confirmed",
                            is_auto=True,
                            is_manual=False,
                        ))
                        continue

                    booking.client = customer
                    booking.ticket_no = row["ticket_no"]
                    booking.passenger_name = row["passenger_name"]
                    booking.sector = row["sector"]
                    booking.travel_date = row["travel_date"]
                    booking.end_date = row["end_date"]
                    booking.booked_date = row["booked_date"]
                    booking.net_amount = final_amount
                    booking.base_amount = row["base_amount"]
                    booking.discount_percentage = discount_percentage
                    booking.airline = row["airline"]
                    booking.fare_type = row["fare_type"]
                    booking.airline_pnr = row["airline_pnr"]
                    booking.booking_type = row["booking_type"]
                    booking.travel_type = row["travel_type"]
                    booking.is_auto = True
                    booking.is_manual = False
                    booking.status = row["status"] or "Confirmed"
                    if booking.status == "Cancelled":
                        _cancel_booking_and_revoke_coupon(booking)
                    else:
                        booking.save(update_fields=[
                            "client", "ticket_no", "passenger_name", "sector",
                            "travel_date", "end_date", "booked_date", "net_amount",
                            "base_amount", "discount_percentage", "airline", "fare_type",
                            "airline_pnr", "booking_type", "travel_type", "status",
                            "is_auto", "is_manual", "updated_at",
                        ])
                    updated += 1

                Booking.objects.bulk_create(new_bookings, batch_size=500)
                added = len(new_bookings)
                imported_bookings = list(
                    Booking.objects.select_related("client").filter(
                        ticket_no__in=[row["ticket_no"] for row in rows_to_import]
                    )
                )
                imported_booking_ids = [booking.pk for booking in imported_bookings]
                bookings_with_coupons = set(
                    Coupon.objects.filter(
                        booking_id__in=imported_booking_ids
                    ).values_list("booking_id", flat=True)
                )
                now_date = timezone.localdate()
                coupons_to_create = []
                ledger_entries_to_create = []
                released_count = 0
                pending_count = 0
                for booking in imported_bookings:
                    if booking.status == "Cancelled" or decimal_value(booking.net_amount) <= 0:
                        continue
                    if booking.pk in bookings_with_coupons:
                        continue

                    points = (decimal_value(booking.net_amount) / Decimal("100")).quantize(
                        Decimal("0.01")
                    )
                    if points <= 0:
                        continue

                    available_now = bool(booking.travel_date and now_date > booking.travel_date)
                    status = "AVAILABLE" if available_now else "PENDING"
                    coupon_id = new_id("CPN")
                    coupon_code = f"CPN-{coupon_id.split('-', 1)[-1]}"
                    txn_id = new_id("TXN-EARN")
                    coupons_to_create.append(Coupon(
                        id=coupon_id,
                        coupon_code=coupon_code,
                        customer=booking.client,
                        booking=booking,
                        booking_ref=booking.pnr,
                        customer_name=booking.client.name,
                        passenger_name=booking.passenger_name,
                        travel_date=booking.travel_date,
                        amount=points,
                        status=status,
                        is_released=available_now,
                        unlock_date=booking.travel_date,
                        available_date=now_date if available_now else None,
                        redeemed_amount=0,
                    ))
                    ledger_entries_to_create.append(Ledger(
                        id=txn_id,
                        txn_id=txn_id,
                        customer=booking.client,
                        customer_name=booking.client.name,
                        booking=booking,
                        booking_ref=booking.pnr,
                        coupon_code=coupon_code,
                        type="Coupon Earned",
                        amount=points,
                        status=status,
                        date=now_date,
                    ))
                    if available_now:
                        released_count += 1
                    else:
                        pending_count += 1

                if coupons_to_create:
                    Coupon.objects.bulk_create(coupons_to_create, batch_size=500)
                if ledger_entries_to_create:
                    Ledger.objects.bulk_create(ledger_entries_to_create, batch_size=500)

            skip_msg = f", {duplicate_skipped} duplicate row(s) skipped" if duplicate_skipped else ""
            messages.success(request, "Booking Added Successfully")
            messages.info(
                request,
                f"Excel upload complete: {added} booking(s) added and {updated} booking(s) updated{skip_msg}; "
                f"{len(coupons_to_create)} coupon(s) earned, {released_count} released and "
                f"{pending_count} pending until travel date.",
            )
        except Exception:
            logger.exception("Excel booking upload failed")
            err_msg = "The workbook could not be imported. Check that it is a valid .xlsx file and each passenger has a valid net amount."
            if is_scan:
                return JsonResponse({"success": False, "error": err_msg}, status=400)
            _add_excel_upload_failure(request, err_msg)
            return redirect("excel_upload")
        finally:
            if workbook is not None:
                workbook.close()

        return redirect("excel_upload")

    return render(request, "excel_upload.html", page_context(request))


@admin_required
def download_excel_template(request):
    from openpyxl import Workbook

    workbook = Workbook()
    ws = workbook.active
    ws.title = "Bookings"

    headers = [
        "S PNR",
        "Client ID",
        "Ticket No",
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
        "Status",
    ]
    ws.append(headers)

    for col in ws.columns:
        max_length = 0
        column = col[0].column_letter
        for cell in col:
            value = cell.value
            if value is not None:
                max_length = max(max_length, len(str(value)))
        ws.column_dimensions[column].width = max(18, max_length + 2)

    response = HttpResponse(content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    response["Content-Disposition"] = 'attachment; filename="coupon_booking_template.xlsx"'
    workbook.save(response)
    workbook.close()
    return response


@admin_required
def rules(request):
    return render(request, "rules.html", page_context(request, rules=read("rules"), airlines=AIRLINES, airline_types=AIRLINE_TYPES))


@admin_required
@require_POST
def add_rule(request):
    airline = request.POST.get("airline", "").strip() or "ANY AIRLINE"
    airline_type = request.POST.get("fare_type", "ANY CLASS").strip() or "ANY CLASS"
    flat_price = request.POST.get("flat_price", "").strip()
    try:
        price_range = _parse_flat_price_range(flat_price)
    except ValueError as exc:
        messages.error(request, str(exc))
        return redirect("rules")
    if price_range is None:
        messages.error(request, "Flat Price range is required.")
        return redirect("rules")
    flat_price = f"{price_range[0]:f} - {price_range[1]:f}"
    try:
        percentage = money(request.POST.get("percentage", 0))
    except (TypeError, ValueError):
        percentage = 0
    if percentage < 0 or percentage > 100:
        messages.error(request, "Discount percentage must be between 0 and 100.")
        return redirect("rules")
    rules_data = read("rules")
    rules_data.append({
        "id": new_id("RULE"),
        "airline": airline,
        "fare_type": airline_type,
        "flat_price": flat_price,
        "percentage": percentage,
        "status": request.POST.get("status", "Active"),
    })
    write("rules", rules_data)
    messages.success(request, "Rule created successfully.")
    return redirect("rules")


@admin_required
@require_POST
def delete_rule(request):
    rid = request.POST.get("id", "").strip()
    rules_data = read("rules")
    write("rules", [r for r in rules_data if r.get("id") != rid])
    messages.success(request, "Rule deleted.")
    return redirect("rules")

@admin_required
def settings_page(request):
    config = {
        "min_redemption_amount": 100,
        "max_redemption_amount": 50000,
        "coupon_expiry_days": 365,
        "allow_partial_redemption": "Yes",
        "allow_combined_offers": "No",
        **(read("settings") or {}),
    }
    return render(request, "settings.html", page_context(request, config=config))


@admin_required
@require_POST
def save_settings(request):
    try:
        expiry_days = max(1, int(request.POST.get("coupon_expiry_days", 365)))
    except (TypeError, ValueError):
        expiry_days = 365

    minimum = money(request.POST.get("min_redemption_amount", 100))
    maximum = money(request.POST.get("max_redemption_amount", 50000))
    if maximum < minimum:
        messages.error(request, "Maximum redemption amount cannot be less than the minimum amount.")
        return redirect("settings")

    config = {
        "min_redemption_amount": minimum,
        "max_redemption_amount": maximum,
        "coupon_expiry_days": expiry_days,
        "allow_partial_redemption": request.POST.get("allow_partial_redemption", "Yes"),
        "allow_combined_offers": request.POST.get("allow_combined_offers", "No"),
    }
    write("settings", config)
    messages.success(request, "Settings saved.")
    return redirect("settings")
