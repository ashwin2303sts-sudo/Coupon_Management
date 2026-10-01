from datetime import date, timedelta
from functools import wraps

from django.contrib import messages
from django.contrib.auth.hashers import check_password, make_password
from django.core.paginator import Paginator
from django.http import HttpResponse
from django.shortcuts import render, redirect
from django.views.decorators.http import require_POST
from django.db import transaction
from django.utils import timezone

from .decorators import admin_required
from .models import Coupon, Redemption, RedemptionAllocation, Ledger, Customer, Booking
from .storage import read, write, now, new_id, money, decimal_value, date_value, get_or_create_customer


def calculate_coupon(booking):
    """Calculate coupon points from the passenger booking amount.

    100 booking currency units = 1 coupon point.  The existing rule object is
    returned for backward compatibility, but the point calculation is no
    longer percentage-based.
    """
    amount = money(booking.get("net_amount"))
    points = round(amount / 100, 2)
    rules = [r for r in read("rules") if r.get("status") == "Active"]
    rule = rules[0] if rules else None
    return points, rule


def _coupon_points(coupon, bookings=None):
    """Return stored points, with a safe fallback for older coupon records."""
    if coupon.get("points") is not None:
        return money(coupon.get("points"))
    if bookings is None:
        bookings = read("bookings")
    booking = next((b for b in bookings if b.get("s_pnr") == coupon.get("booking_ref")), None)
    if booking:
        return money(booking.get("net_amount")) / 100
    return 0.0


def _coupon_status_for_travel(coupon, bookings=None):
    """Pending before travel start; available on/after travel start."""
    if coupon.get("status") == "REDEEMED":
        return "REDEEMED"
    if bookings is None:
        bookings = read("bookings")
    booking = next((b for b in bookings if b.get("s_pnr") == coupon.get("booking_ref")), None)
    travel_date = (booking or {}).get("travel_date") or coupon.get("travel_start_date") or coupon.get("unlock_date")
    if not travel_date:
        return "PENDING"
    try:
        return "AVAILABLE" if timezone.localdate() >= date.fromisoformat(str(travel_date)[:10]) else "PENDING"
    except ValueError:
        return "PENDING"


def auto_release_coupons():
    coupons = read("coupons")
    bookings = read("bookings")
    changed = False

    for c in coupons:
        status = _coupon_status_for_travel(c, bookings)
        points = _coupon_points(c, bookings)
        if c.get("points") != points:
            c["points"] = points
            changed = True
        if c.get("status") != status and c.get("status") != "REDEEMED":
            c["status"] = status
            changed = True
        released = status == "AVAILABLE" or c.get("status") == "REDEEMED"
        if bool(c.get("is_released")) != released:
            c["is_released"] = released
            changed = True
        booking = next((b for b in bookings if b.get("s_pnr") == c.get("booking_ref")), None)
        if booking and c.get("travel_start_date") != booking.get("travel_date", ""):
            c["travel_start_date"] = booking.get("travel_date", "")
            changed = True
        if booking and c.get("travel_end_date") != booking.get("end_date", ""):
            c["travel_end_date"] = booking.get("end_date", "")
            changed = True
        if booking and c.get("passenger_id") != booking.get("passenger_id", ""):
            c["passenger_id"] = booking.get("passenger_id", "")
            c["passenger_name"] = booking.get("passenger_name", "")
            changed = True

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

    all_bookings = read("bookings")
    for booking in all_bookings:
        if booking.get("booking_type") in {"Round Trip", "One Way"} and not booking.get("travel_type"):
            booking["travel_type"] = booking["booking_type"]
            booking["booking_type"] = "Web Booking"
        booking.setdefault("booking_type", "Web Booking")
        booking.setdefault("travel_type", "")
    bookings = [b for b in all_bookings if not selected_id or b.get("client_id") == selected_id]
    passenger_keys = {
        str(b.get("passenger_id") or b.get("passenger_name") or b.get("s_pnr") or "").strip().casefold()
        for b in bookings
    }
    passenger_keys.discard("")
    all_coupons = auto_release_coupons()
    coupons = [c for c in all_coupons if not selected_id or c.get("customer_id") == selected_id]
    available = sum(_coupon_points(c, all_bookings) for c in coupons if c.get("status") == "AVAILABLE")
    pending = sum(_coupon_points(c, all_bookings) for c in coupons if c.get("status") == "PENDING")
    total_coupon_points = available + pending
    earned = sum(_coupon_points(c, all_bookings) for c in coupons if c.get("status") in ["PENDING", "AVAILABLE", "REDEEMED"])
    customer_count = 1 if customer else len(customers)
    client_summaries = []
    for client in customers:
        client_bookings = [b for b in all_bookings if b.get("client_id") == client.get("id")]
        client_passenger_keys = {
            str(b.get("passenger_id") or b.get("passenger_name") or b.get("s_pnr") or "").strip().casefold()
            for b in client_bookings
        }
        client_passenger_keys.discard("")
        client_summaries.append({**client, "passenger_count": len(client_passenger_keys)})
    if client_query:
        client_summaries = [
            client for client in client_summaries
            if client_query.casefold() in str(client.get("id", "")).casefold()
        ]

    passenger_query = request.GET.get("passenger_id", "").strip()
    passenger_matches = [
        b for b in bookings
        if not passenger_query or passenger_query.casefold() in " ".join((
            str(b.get("passenger_id", "")), str(b.get("passenger_name", ""))
        )).casefold()
    ]
    selected_passenger_id = request.GET.get("selected_passenger", "").strip()
    selected_booking = next(
        (b for b in bookings if b.get("s_pnr") == selected_passenger_id), None
    )
    passenger_history = []
    passenger_points = 0
    if selected_booking:
        passenger_name = str(selected_booking.get("passenger_name") or "").strip()
        passenger_id = str(selected_booking.get("passenger_id") or "").strip()
        passenger_history = [
            dict(b) for b in bookings
            if passenger_id and str(b.get("passenger_id") or "").strip().casefold() == passenger_id.casefold()
            or not passenger_id and passenger_name and str(b.get("passenger_name") or "").strip().casefold() == passenger_name.casefold()
        ] or [dict(selected_booking)]
        for trip in passenger_history:
            trip["history_end_date"] = trip.get("end_date") or trip.get("travel_date") or "-"
            trip["trip_status"] = (
                "INACTIVE" if trip.get("travel_date") and trip["travel_date"] < date.today().isoformat()
                else "ACTIVE"
            )
        passenger_coupons = [
            c for c in all_coupons
            if str(c.get("passenger_id") or "").strip().casefold() == passenger_id.casefold()
            or (not passenger_id and str(c.get("passenger_name") or "").strip().casefold() == passenger_name.casefold())
            or c.get("booking_ref") in {h.get("s_pnr") for h in passenger_history}
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
        passenger_count=len(passenger_keys),
        passenger_matches=passenger_matches,
        passenger_query=passenger_query,
        selected_passenger_id=selected_passenger_id,
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
                "passenger_id": customer.get("passenger_id", "-"),
                "booking_type": "-",
                "travel_type": "-",
                "travel_start": "-",
                "travel_end": "-",
                "booked_date": "-",
                "amount": 0,
                "edit_passenger_id": customer.get("passenger_id", ""),
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
                "passenger_id": booking.get("passenger_id") or customer.get("passenger_id", "-"),
                "booking_type": booking_type,
                "travel_type": travel_type,
                "travel_start": booking.get("travel_date") or "-",
                "travel_end": booking.get("end_date") or booking.get("travel_date") or "-",
                "booked_date": booking.get("booked_date") or "-",
                "amount": money(booking.get("net_amount")),
                "edit_passenger_id": customer.get("passenger_id", ""),
            })

    return render(request, "customers.html", page_context(request, customers=customer_rows))


@admin_required
@require_POST
def add_customer(request):
    customers = read("customers")
    redirect_to = "bookings" if request.POST.get("return_to") == "bookings" else "customers"
    customer_id = request.POST.get("id", "").strip()
    passenger_id = request.POST.get("passenger_id", "").strip()
    name = request.POST.get("name", "").strip()
    email = request.POST.get("email", "").strip()
    phone = request.POST.get("phone", "").strip()

    if not all((customer_id, passenger_id, name, email, phone)):
        messages.error(request, "Client ID, Passenger ID, name, email, and phone are required.")
        return redirect(redirect_to)

    if any(c["id"] == customer_id for c in customers):
        messages.error(request, "Customer ID already exists.")
        return redirect(redirect_to)

    customers.insert(0, {
        "id": customer_id,
        "passenger_id": passenger_id,
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
    passenger_id = request.POST.get("passenger_id", "").strip()
    name = request.POST.get("name", "").strip()
    email = request.POST.get("email", "").strip()
    phone = request.POST.get("phone", "").strip()
    if not all((passenger_id, name, email, phone)):
        messages.error(request, "Passenger ID, name, email, and phone are required.")
        return redirect("customers")
    customer.update({
        "passenger_id": passenger_id,
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
    travel_types = {"Round Trip", "One Way"}
    for booking in data:
        if booking.get("booking_type") in travel_types and not booking.get("travel_type"):
            booking["travel_type"] = booking["booking_type"]
            booking["booking_type"] = "Web Booking"
        booking.setdefault("booking_type", "Web Booking")
        booking.setdefault("travel_type", "")
    if q:
        data = [
            b for b in data
            if q in str(b).lower()
        ]
    return render(request, "bookings.html", page_context(
        request,
        bookings=data,
        search=q,
        customers=read("customers"),
    ))


@admin_required
@require_POST
def add_booking(request):
    bookings = read("bookings")
    customers = read("customers")
    client_id = request.POST.get("client_id", "").strip()
    client_name = request.POST.get("client_name", "").strip()

    # Look up customer; if not found, use the typed name/id directly
    client_record = next((c for c in customers if c.get("id") == client_id), None)
    if not client_name and client_record:
        client_name = client_record.get("name", client_id)
    if not client_name:
        client_name = client_id

    booking = {
        "s_pnr": request.POST.get("s_pnr", "").strip(),
        "passenger_id": request.POST.get("passenger_id", "").strip(),
        "passenger_name": request.POST.get("passenger_name", "").strip(),
        "client": client_name,
        "client_id": client_id,
        "sector": request.POST.get("sector", "").strip(),
        "booking_type": request.POST.get("booking_type", "Web Booking").strip(),
        "travel_type": request.POST.get("travel_type", "One Way").strip(),
        "airline_pnr": request.POST.get("airline_pnr", "").strip(),
        "net_amount": money(request.POST.get("net_amount", 0)),
        "travel_date": request.POST.get("travel_date", ""),
        "end_date": request.POST.get("end_date", ""),
        "booked_date": request.POST.get("booked_date", date.today().isoformat()),
    }
    if not booking["s_pnr"] or not booking["passenger_id"] or not client_record:
        messages.error(request, "S PNR, Passenger ID, and a valid Client ID are required.")
        return redirect("bookings")
    if any(b.get("s_pnr") == booking["s_pnr"] for b in bookings):
        messages.error(request, "This S PNR already exists.")
        return redirect("bookings")

    bookings.insert(0, booking)
    write("bookings", bookings)

    messages.success(request, "Booking added successfully. Go to Coupons and earn the coupon for this booking.")

    return redirect("bookings")


@admin_required
@require_POST
def edit_booking(request):
    bookings_data = read("bookings")
    customers = read("customers")
    spnr = request.POST.get("s_pnr", "").strip()
    booking = next((b for b in bookings_data if b.get("s_pnr") == spnr), None)
    if not booking:
        messages.error(request, "Booking not found.")
        return redirect("bookings")
    passenger_id = request.POST.get("passenger_id", "").strip()
    client_id = request.POST.get("client_id", "").strip()
    client_record = next((c for c in customers if c.get("id") == client_id), None)
    if not passenger_id or not client_record:
        messages.error(request, "Passenger ID and a valid client are required.")
        return redirect("bookings")
    booking.update({
        "passenger_id": passenger_id,
        "passenger_name": request.POST.get("passenger_name", booking.get("passenger_name", "")).strip(),
        "client": client_record["name"],
        "client_id": client_id,
        "sector": request.POST.get("sector", "").strip(),
        "booking_type": request.POST.get("booking_type", "Web Booking"),
        "travel_type": request.POST.get("travel_type", "One Way"),
        "airline_pnr": request.POST.get("airline_pnr", "").strip(),
        "net_amount": money(request.POST.get("net_amount", 0)),
        "travel_date": request.POST.get("travel_date", ""),
        "end_date": request.POST.get("end_date", ""),
        "booked_date": request.POST.get("booked_date", ""),
    })
    write("bookings", bookings_data)
    messages.success(request, "Booking updated successfully.")
    return redirect("bookings")

@admin_required
@require_POST
def delete_booking(request):
    spnr = request.POST.get("s_pnr", "").strip()
    bookings_data = read("bookings")
    write("bookings", [b for b in bookings_data if b.get("s_pnr") != spnr])
    messages.success(request, "Booking deleted.")
    return redirect("bookings")

@admin_required
def coupons(request):
    bookings_data = read("bookings")
    coupon_data = auto_release_coupons()
    available_points = sum(_coupon_points(c, bookings_data) for c in coupon_data if c.get("status") == "AVAILABLE")
    pending_points = sum(_coupon_points(c, bookings_data) for c in coupon_data if c.get("status") == "PENDING")
    return render(request, "coupons.html", page_context(
        request,
        coupons=coupon_data,
        customers=read("customers"),
        bookings=bookings_data,
        available_points=available_points,
        pending_points=pending_points,
        total_coupon_points=available_points + pending_points,
    ))


@admin_required
@require_POST
def earn_coupon(request):
    customer_id = request.POST.get("customer_id", "").strip()
    booking_ref = request.POST.get("booking_ref", "").strip()

    if not customer_id or not booking_ref:
        messages.error(request, "Customer ID and Booking Reference are required.")
        return redirect("coupons")

    customer = Customer.objects.filter(id=customer_id).first()
    booking = Booking.objects.select_related("client").filter(pnr=booking_ref).first()

    if not booking:
        messages.error(request, "Booking reference not found.")
        return redirect("coupons")
    if not customer:
        messages.error(request, "Customer ID not found.")
        return redirect("coupons")
    if booking.client_id != customer_id:
        messages.error(request, "This booking does not belong to the selected customer.")
        return redirect("coupons")

    if Coupon.objects.filter(booking_ref=booking_ref).exists():
        existing = Coupon.objects.filter(booking_ref=booking_ref).first()
        messages.info(request, f"A coupon already exists for {booking_ref} ({existing.status}).")
        return redirect("coupons")

    amount = money(booking.net_amount)
    points = round(amount / 100, 2)
    if points <= 0:
        messages.error(request, "Booking amount must be greater than ₹0 to earn coupon points.")
        return redirect("coupons")

    travel_start = booking.travel_date
    available_now = bool(travel_start and timezone.localdate() >= travel_start)
    status = "AVAILABLE" if available_now else "PENDING"
    coupon_id = new_id("CPN")
    coupon_code = f"CPN-{coupon_id.split('-', 1)[-1]}"

    with transaction.atomic():
        Coupon.objects.create(
            id=coupon_id,
            coupon_code=coupon_code,
            customer=customer,
            booking=booking,
            booking_ref=booking_ref,
            customer_name=customer.name,
            passenger_name=booking.passenger_name,
            travel_date=travel_start,
            amount=points,
            status=status,
            is_released=available_now,
            unlock_date=travel_start,
            available_date=timezone.localdate() if available_now else None,
            redeemed_amount=0,
        )

        Ledger.objects.create(
            id=new_id("TXN-EARN"),
            txn_id=new_id("TXN-EARN"),
            customer=customer,
            customer_name=customer.name,
            booking=booking,
            booking_ref=booking_ref,
            coupon_code=coupon_code,
            type="Coupon Earned",
            amount=points,
            status=status,
            date=timezone.localdate(),
        )

    messages.success(request, f"Coupon earned: {points:.2f} points (₹{amount:.2f} ÷ 100).")
    return redirect("coupons")


@admin_required
@require_POST
def release_coupon(request):
    booking_ref = request.POST.get("booking_ref", "").strip()
    booking = Booking.objects.filter(pnr=booking_ref).first()
    if not booking:
        messages.error(request, "Booking reference not found.")
        return redirect("coupons")

    if not booking.travel_date:
        messages.warning(request, "The booking does not have a travel start date.")
        return redirect("coupons")
    if timezone.localdate() < booking.travel_date:
        messages.warning(request, "This coupon cannot be released before the travel start date.")
        return redirect("coupons")

    coupon = Coupon.objects.filter(booking_ref=booking_ref).first()
    if not coupon:
        messages.warning(request, "No coupon found for that booking. Earn the coupon first.")
        return redirect("coupons")
    if coupon.status == "REDEEMED":
        messages.warning(request, "This coupon has already been redeemed.")
        return redirect("coupons")

    coupon.status = "AVAILABLE"
    coupon.is_released = True
    coupon.available_date = timezone.localdate()
    coupon.save(update_fields=["status", "is_released", "available_date", "updated_at"])

    Ledger.objects.create(
        id=new_id("TXN-REL"),
        txn_id=new_id("TXN-REL"),
        customer=coupon.customer,
        customer_name=coupon.customer.name if coupon.customer else coupon.customer_name,
        booking=booking,
        booking_ref=booking_ref,
        coupon_code=coupon.coupon_code or coupon.id,
        type="Coupon Released",
        amount=0,
        status="AVAILABLE",
        date=timezone.localdate(),
    )

    messages.success(request, "Coupon is now AVAILABLE because the travel date has started.")
    return redirect("coupons")


@admin_required
@require_POST
def redeem_coupon(request):
    customer_id = request.POST.get("customer_id", "").strip()
    booking_ref = request.POST.get("booking_ref", "").strip()

    customer = Customer.objects.filter(id=customer_id).first()
    if not customer:
        messages.error(request, "Customer ID not found.")
        return redirect("coupons")

    if not Booking.objects.filter(pnr=booking_ref).exists():
        messages.error(request, "Next Booking / PNR not found.")
        return redirect("coupons")

    config = read("settings")
    minimum = money(config.get("min_redemption_amount", 100))
    maximum = money(config.get("max_redemption_amount", 50000))

    available = list(
        Coupon.objects.select_related("customer", "booking")
        .filter(customer_id=customer_id, status="AVAILABLE")
        .order_by("created_at")
    )
    available = [c for c in available if money(c.amount) > 0]
    if not available:
        messages.error(request, "No available coupon balance for this customer.")
        return redirect("coupons")

    total_available = sum(money(c.amount) for c in available)
    if total_available < minimum:
        messages.error(request, f"Available coupon amount must be at least ₹{minimum:.2f}.")
        return redirect("coupons")

    redeemed_amount = min(total_available, maximum)
    remaining = redeemed_amount
    allocations = []

    with transaction.atomic():
        for coupon in available:
            if remaining <= 0:
                break
            used = min(money(coupon.amount), remaining)
            if used <= 0:
                continue

            coupon.amount = decimal_value(coupon.amount) - decimal_value(used)
            coupon.redeemed_amount = decimal_value(coupon.redeemed_amount) + decimal_value(used)
            coupon.is_released = True
            if money(coupon.amount) <= 0:
                coupon.amount = 0
                coupon.status = "REDEEMED"
            else:
                coupon.status = "AVAILABLE"
            coupon.save(update_fields=["amount", "redeemed_amount", "status", "is_released", "updated_at"])

            code = coupon.coupon_code or coupon.id
            allocations.append((coupon, code, used))
            remaining = money(remaining - used)

        redemption_id = new_id("RDM")
        redemption = Redemption.objects.create(
            id=redemption_id,
            customer=customer,
            customer_name=customer.name,
            booking_ref=booking_ref,
            coupon_code=", ".join(code for _, code, _ in allocations),
            amount=redeemed_amount,
            redeemed_amount=redeemed_amount,
            status="COMPLETED",
            redemption_type="Coupon Redemption",
            time=now().split(" ")[1][:5],
        )

        for _, code, used in allocations:
            RedemptionAllocation.objects.create(
                redemption=redemption,
                coupon_code=code,
                amount=used,
            )

        Ledger.objects.create(
            id=new_id("TXN-RED"),
            txn_id=redemption_id,
            customer=customer,
            customer_name=customer.name,
            booking_ref=booking_ref,
            coupon_code=redemption.coupon_code,
            type="Coupon Redeemed",
            amount=-decimal_value(redeemed_amount),
            status="SUCCESS",
            date=date.today(),
        )

    messages.success(request, f"Coupon redeemed successfully: ₹{redeemed_amount:.2f}")
    return redirect("coupons")


@admin_required
@require_POST
def reverse_coupon(request):
    booking_ref = request.POST.get("booking_ref", "").strip()
    if not booking_ref:
        messages.error(request, "Booking reference is required.")
        return redirect("coupons")

    redemption = (
        Redemption.objects.prefetch_related("allocations")
        .filter(booking_ref=booking_ref, status__in=["COMPLETED", "SUCCESS"])
        .order_by("-date")
        .first()
    )
    if not redemption:
        messages.error(request, "No completed redemption was found for this booking reference.")
        return redirect("coupons")

    with transaction.atomic():
        restored = decimal_value(0)
        allocations = list(redemption.allocations.all())

        if allocations:
            for allocation in allocations:
                coupon = Coupon.objects.filter(coupon_code=allocation.coupon_code).first()
                if not coupon:
                    continue
                add_back = decimal_value(allocation.amount)
                coupon.amount = decimal_value(coupon.amount) + add_back
                coupon.redeemed_amount = max(decimal_value(0), decimal_value(coupon.redeemed_amount) - add_back)
                coupon.status = "AVAILABLE"
                coupon.is_released = True
                coupon.save(update_fields=["amount", "redeemed_amount", "status", "is_released", "updated_at"])
                restored += add_back
        else:
            codes = [x.strip() for x in str(redemption.coupon_code or "").split(",") if x.strip()]
            for code in codes:
                coupon = Coupon.objects.filter(coupon_code=code).first()
                if coupon:
                    add_back = decimal_value(redemption.redeemed_amount)
                    coupon.amount = decimal_value(coupon.amount) + add_back
                    coupon.redeemed_amount = max(decimal_value(0), decimal_value(coupon.redeemed_amount) - add_back)
                    coupon.status = "AVAILABLE"
                    coupon.is_released = True
                    coupon.save(update_fields=["amount", "redeemed_amount", "status", "is_released", "updated_at"])
                    restored += add_back
                    break

        if restored <= 0:
            messages.error(request, "No matching coupon record was found to reverse.")
            return redirect("coupons")

        redemption.status = "REVERSED"
        redemption.reversed_at = timezone.now()
        redemption.reversed_amount = restored
        redemption.save(update_fields=["status", "reversed_at", "reversed_amount"])

        Ledger.objects.create(
            id=new_id("TXN-REV"),
            txn_id=new_id("TXN-REV"),
            customer=redemption.customer,
            customer_name=redemption.customer_name,
            booking_ref=booking_ref,
            coupon_code=redemption.coupon_code,
            type="Coupon Reversed",
            amount=restored,
            status="REVERSED",
            date=date.today(),
        )

    messages.success(request, f"Coupon redemption reversed: ₹{float(restored):.2f} restored.")
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
                "txn_id", "customer_id", "customer_name", "booking_ref", "type", "coupon_code"
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

    page_obj = Paginator(filtered, 10).get_page(request.GET.get("page"))
    transaction_types = sorted({row["type"] for row in transactions if row["type"]})
    return render(request, "ledger.html", page_context(
        request,
        ledger=page_obj.object_list,
        page_obj=page_obj,
        search=search,
        transaction_type=transaction_type,
        from_date=from_date,
        to_date=to_date,
        transaction_types=transaction_types,
        start_index=page_obj.start_index() if page_obj.object_list else 0,
        end_index=page_obj.end_index() if page_obj.object_list else 0,
        total_count=len(filtered),
        total_earned=total_earned,
        total_redeemed=total_redeemed,
        total_available=total_available,
        total_transactions=total_transactions,
    ))


@admin_required
def excel_upload(request):
    if request.method == "POST":
        upload = request.FILES.get("excel_file")
        if not upload:
            messages.error(request, "Please select an Excel file.")
            return redirect("excel_upload")

        workbook = None
        try:
            from openpyxl import load_workbook
            workbook = load_workbook(upload, read_only=True, data_only=True)
            ws = workbook.active
            headers = [str(c.value).strip() if c.value is not None else "" for c in ws[1]]

            required = {"Client ID", "S PNR"}
            missing = required - set(headers)
            if missing:
                messages.error(request, "Missing required columns: " + ", ".join(sorted(missing)))
                return redirect("excel_upload")

            existing_pnrs = set(Booking.objects.values_list("pnr", flat=True))
            imported_pnrs = set()
            rows_to_import = []

            for values in ws.iter_rows(min_row=2, values_only=True):
                row = dict(zip(headers, values))
                spnr = str(row.get("S PNR") or "").strip()
                client_id = str(row.get("Client ID") or "").strip()
                if not spnr or not client_id:
                    continue
                if spnr in existing_pnrs or spnr in imported_pnrs:
                    continue
                imported_pnrs.add(spnr)

                client = str(row.get("Client") or client_id).strip()
                legacy_type = str(row.get("Booking Type") or "").strip()
                booking_method = str(row.get("Booking Method") or "").strip()
                if not booking_method:
                    booking_method = legacy_type if legacy_type in {"Web Booking", "Mobile App", "Agent Booking", "Offline/Counter"} else "Web Booking"
                travel_type = str(row.get("Travel Type") or "").strip()
                if not travel_type and legacy_type in {"Round Trip", "One Way"}:
                    travel_type = legacy_type
                rows_to_import.append({
                    "s_pnr": spnr,
                    "client_id": client_id,
                    "client": client,
                    "email": str(row.get("Email") or ""),
                    "mobile": str(row.get("Mobile") or ""),
                    "passenger_id": str(row.get("Passenger ID") or "").strip(),
                    "passenger_name": str(row.get("Pax Name") or "").strip(),
                    "sector": str(row.get("Sector") or "").strip(),
                    "booking_type": booking_method,
                    "travel_type": travel_type,
                    "airline_pnr": str(row.get("Airline PNR") or "").strip(),
                    "status": str(row.get("Status") or "Confirmed").strip(),
                    "net_amount": money(row.get("Net Amount") or 0),
                    "travel_date": date_value(row.get("Travel Start Date") or row.get("Date of Travel")),
                    "end_date": date_value(row.get("Travel End Date")),
                    "booked_date": date_value(row.get("Booked Date")) or timezone.localdate(),
                })

            with transaction.atomic():
                customers_by_id = Customer.objects.in_bulk({row["client_id"] for row in rows_to_import})
                new_bookings = []
                for row in rows_to_import:
                    customer = customers_by_id.get(row["client_id"])
                    if customer is None:
                        customer = get_or_create_customer(row)
                        customers_by_id[row["client_id"]] = customer
                    new_bookings.append(Booking(
                        pnr=row["s_pnr"],
                        client=customer,
                        passenger_name=row["passenger_name"],
                        passenger_id=row["passenger_id"] or None,
                        sector=row["sector"] or None,
                        travel_date=row["travel_date"],
                        end_date=row["end_date"],
                        booked_date=row["booked_date"],
                        net_amount=row["net_amount"],
                        email=row["email"] or None,
                        mobile=row["mobile"] or None,
                        airline_pnr=row["airline_pnr"] or None,
                        status=row["status"],
                        booking_type=row["booking_type"],
                        travel_type=row["travel_type"],
                    ))
                Booking.objects.bulk_create(new_bookings, batch_size=500)
                added = len(new_bookings)

            messages.success(request, f"Upload completed. {added} new booking(s) added.")
        except Exception as exc:
            messages.error(request, f"Excel processing error: {exc}")
            return redirect("excel_upload")
        finally:
            if workbook is not None:
                workbook.close()

        return redirect("bookings")

    return render(request, "excel_upload.html", page_context(request))


@admin_required
def rules(request):
    return render(request, "rules.html", page_context(request, rules=read("rules")))


@admin_required
@require_POST
def add_rule(request):
    rules_data = read("rules")
    rules_data.append({
        "id": new_id("RULE"),
        "office_id": request.POST.get("office_id", "").strip(),
        "booking_type": request.POST.get("booking_type", "Any Booking Type"),
        "supplier": request.POST.get("supplier", "").strip(),
        "airline": request.POST.get("airline", "").strip(),
        "fare_type": request.POST.get("fare_type", "Any Fare Type"),
        "percentage": money(request.POST.get("percentage", 2.5)),
        "status": request.POST.get("status", "Active"),
    })
    write("rules", rules_data)
    messages.success(request, "Rule created.")
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
