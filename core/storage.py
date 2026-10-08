import uuid
from datetime import datetime, date
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from .models import (
    User,
    Customer,
    Booking,
    Coupon,
    Redemption,
    RedemptionAllocation,
    Ledger,
    Rule,
    Setting,
)


# =========================================================
# HELPER FUNCTIONS
# =========================================================

def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def new_id(prefix):
    return f"{prefix}-{uuid.uuid4().hex[:10].upper()}"


def money(value):
    try:
        return round(float(value or 0), 2)
    except (TypeError, ValueError):
        return 0.0


def decimal_value(value):
    try:
        return Decimal(str(value or 0))
    except (TypeError, ValueError, ArithmeticError):
        return Decimal("0")


def date_value(value):
    if not value:
        return None

    if isinstance(value, date):
        return value

    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def datetime_value(value):
    if not value:
        return timezone.now()

    if isinstance(value, datetime):
        return value

    try:
        value = str(value).replace("Z", "+00:00")
        dt = datetime.fromisoformat(value)

        if timezone.is_naive(dt):
            dt = timezone.make_aware(dt)

        return dt

    except (TypeError, ValueError):
        return timezone.now()


def boolean_value(value):
    if isinstance(value, bool):
        return value

    return str(value).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


# =========================================================
# CUSTOMER HELPER
# =========================================================

def get_or_create_customer(data):
    customer_id = (
        data.get("client_id")
        or data.get("customer_id")
        or data.get("id")
    )

    if not customer_id:
        customer_id = new_id("CUS")

    customer_name = (
        data.get("client")
        or data.get("customer_name")
        or data.get("name")
        or "Unknown Customer"
    )

    customer, created = Customer.objects.get_or_create(
        id=customer_id,
        defaults={
            "name": customer_name,
            "email": data.get("email") or None,
            "phone": data.get("phone") or data.get("mobile") or None,
            "status": data.get("status", "ACTIVE"),
        },
    )

    if not created:
        changed = False

        if customer_name and customer.name != customer_name:
            customer.name = customer_name
            changed = True

        if data.get("email") and customer.email != data.get("email"):
            customer.email = data.get("email")
            changed = True

        if data.get("phone") and customer.phone != data.get("phone"):
            customer.phone = data.get("phone")
            changed = True

        if changed:
            customer.save()

    return customer


def find_booking(booking_id=None, ticket_no=None, pnr=None):
    if ticket_no:
        booking = Booking.objects.filter(ticket_no=ticket_no).first()
        if booking:
            return booking

    if booking_id is not None and str(booking_id).isdigit():
        booking = Booking.objects.filter(pk=int(booking_id)).first()
        if booking and (not pnr or booking.pnr == pnr):
            return booking

    if pnr:
        matches = Booking.objects.filter(pnr=pnr)
        if matches.count() == 1:
            return matches.first()
        if matches.exists():
            raise ValueError(
                f"Booking PNR {pnr} matches multiple passengers; provide booking_id or ticket_no."
            )

    return None


# =========================================================
# READ
# =========================================================

def read(name):

    # -----------------------------------------------------
    # USERS
    # -----------------------------------------------------

    if name == "users":

        users = User.objects.all().order_by("username")

        return [
            {
                "id": user.user_id,
                "user_id": user.user_id,
                "username": user.username,
                "password": user.password,
                "name": user.name,
                "role": user.role,
            }
            for user in users
        ]


    # -----------------------------------------------------
    # CUSTOMERS
    # -----------------------------------------------------

    if name == "customers":

        customers = Customer.objects.all().order_by("name")

        return [
            {
                "id": customer.id,
                "customer_id": customer.id,
                "name": customer.name,
                "email": customer.email or "",
                "phone": customer.phone or "",
                "status": customer.status,
                "created_at": (
                    customer.created_at.strftime("%Y-%m-%d %H:%M:%S")
                    if customer.created_at
                    else ""
                ),
                "updated_at": (
                    customer.updated_at.strftime("%Y-%m-%d %H:%M:%S")
                    if customer.updated_at
                    else ""
                ),
            }
            for customer in customers
        ]


    # -----------------------------------------------------
    # BOOKINGS
    # -----------------------------------------------------

    if name == "bookings":

        bookings = Booking.objects.select_related("client").all().order_by(
            "-updated_at", "-created_at"
        )

        result = []

        for booking in bookings:

            result.append(
                {
                    "id": booking.pk,
                    "booking_id": booking.pk,
                    "s_pnr": booking.pnr,
                    "pnr": booking.pnr,
                    "ticket_no": booking.ticket_no or "",

                    "client": booking.client.name if booking.client else "",
                    "client_id": booking.client_id,

                    "passenger_name": booking.passenger_name,

                    "sector": booking.sector or "",

                    "travel_date": (
                        booking.travel_date.isoformat()
                        if booking.travel_date
                        else ""
                    ),

                    "end_date": (
                        booking.end_date.isoformat()
                        if booking.end_date
                        else ""
                    ),

                    "booked_date": (
                        booking.booked_date.isoformat()
                        if booking.booked_date
                        else ""
                    ),

                    "net_amount": money(booking.net_amount),
                    "base_amount": money(booking.base_amount),
                    "discount_percentage": money(booking.discount_percentage),

                    "email": booking.email or "",
                    "mobile": booking.mobile or "",
                    "airline_pnr": booking.airline_pnr or "",

                    "status": "Cancelled" if str(booking.status or "").strip().lower() == "cancelled" else "Confirmed",
                    "auto": booking.is_auto,
                    "manual": booking.is_manual,
                    "booking_type": booking.booking_type,
                    "travel_type": booking.travel_type,

                    "username": booking.username or "",
                    "office_id": booking.office_id or "",
                    "supplier": booking.supplier or "",
                    "airline": booking.airline or "",
                    "fare_type": booking.fare_type or "",
                    "parent_pnr": booking.parent_pnr or "",
                }
            )

        return result


    # -----------------------------------------------------
    # COUPONS
    # -----------------------------------------------------

    if name == "coupons":

        coupons = Coupon.objects.select_related(
            "customer",
            "booking",
        ).all().order_by("-created_at")

        booking_ticket_map = {
            b.pk: (b.ticket_no or "")
            for b in Booking.objects.all()
        }

        result = []

        for coupon in coupons:

            booking_ref = coupon.booking_ref or ""

            if not booking_ref and coupon.booking:
                booking_ref = coupon.booking.pnr

            ticket_no = ""
            if coupon.booking and coupon.booking.ticket_no:
                ticket_no = coupon.booking.ticket_no
            elif coupon.booking_id in booking_ticket_map:
                ticket_no = booking_ticket_map[coupon.booking_id]

            result.append(
                {
                    "id": coupon.id,

                    "coupon_code": coupon.coupon_code or coupon.id,

                    "customer_id": (
                        coupon.customer_id
                        if coupon.customer
                        else ""
                    ),

                    "customer_name": (
                        coupon.customer.name
                        if coupon.customer
                        else coupon.customer_name or ""
                    ),

                    "booking_ref": booking_ref,
                    "booking_id": coupon.booking_id or "",
                    "ticket_no": ticket_no,

                    "passenger_name": coupon.passenger_name or "",

                    "travel_date": (
                        coupon.travel_date.isoformat()
                        if coupon.travel_date
                        else ""
                    ),

                    # `amount` represents coupon points/balance in the current UI.
                    "amount": money(coupon.amount),
                    "points": money(coupon.amount),
                    "coupon_amount": money(coupon.amount) / 10,

                    "status": coupon.status,
                    "is_released": bool(coupon.is_released),

                    "available_date": (
                        coupon.available_date.isoformat()
                        if coupon.available_date
                        else ""
                    ),

                    "expiry_date": (
                        coupon.expiry_date.isoformat()
                        if coupon.expiry_date
                        else ""
                    ),

                    "unlock_date": (
                        coupon.unlock_date.isoformat()
                        if coupon.unlock_date
                        else ""
                    ),

                    "travel_start_date": (
                        coupon.travel_date.isoformat()
                        if coupon.travel_date
                        else ""
                    ),
                    "travel_end_date": (
                        coupon.booking.end_date.isoformat()
                        if coupon.booking and coupon.booking.end_date
                        else ""
                    ),
                    "redeemed_amount": money(
                        coupon.redeemed_amount
                    ),

                    "created_at": (
                        coupon.created_at.strftime(
                            "%Y-%m-%d %H:%M:%S"
                        )
                        if coupon.created_at
                        else ""
                    ),
                }
            )

        return result


    # -----------------------------------------------------
    # REDEMPTIONS
    # -----------------------------------------------------

    if name == "redemptions":

        redemptions = Redemption.objects.select_related(
            "customer"
        ).prefetch_related(
            "allocations"
        ).all().order_by("-date")

        result = []

        for redemption in redemptions:

            allocations = []

            for allocation in redemption.allocations.all():

                allocations.append(
                    {
                        "coupon_code": allocation.coupon_code,
                        "amount": money(allocation.amount),
                    }
                )

            result.append(
                {
                    "id": redemption.id,

                    "customer_id": (
                        redemption.customer_id or ""
                    ),

                    "customer_name": (
                        redemption.customer.name
                        if redemption.customer
                        else redemption.customer_name or ""
                    ),

                    "booking_id": redemption.booking_ref or "",
                    "booking_ref": redemption.booking_ref or "",
                    "booking_record_id": redemption.booking_id or "",

                    "coupon_code": redemption.coupon_code or "",

                    "amount": money(redemption.amount),

                    "redeemed_amount": money(
                        redemption.redeemed_amount
                    ),

                    "status": redemption.status,

                    "redemption_type": (
                        redemption.redemption_type or ""
                    ),

                    "date": (
                        redemption.date.strftime(
                            "%Y-%m-%d"
                        )
                        if redemption.date
                        else ""
                    ),

                    "time": redemption.time or "",

                    "notes": redemption.notes or "",

                    "reversed_at": (
                        redemption.reversed_at.strftime(
                            "%Y-%m-%d %H:%M:%S"
                        )
                        if redemption.reversed_at
                        else ""
                    ),

                    "reversed_amount": money(
                        redemption.reversed_amount
                    ),

                    "coupon_allocations": allocations,
                }
            )

        return result


    # -----------------------------------------------------
    # LEDGER
    # -----------------------------------------------------

    if name == "ledger":

        ledger_entries = Ledger.objects.select_related(
            "customer",
            "booking",
        ).all().order_by("-date", "-created_at")

        booking_status_map = {
            b.pk: (
                "Cancelled"
                if str(b.status or "").strip().lower() == "cancelled"
                else "Confirmed"
            )
            for b in Booking.objects.all()
        }

        booking_ticket_map = {
            b.pk: (b.ticket_no or "")
            for b in Booking.objects.all()
        }

        result = []

        for entry in ledger_entries:

            booking_ref = entry.booking_ref or ""

            if not booking_ref and entry.booking:
                booking_ref = entry.booking.pnr

            booking_status = "-"
            ticket_no = ""
            if entry.booking:
                booking_status = (
                    "Cancelled"
                    if str(entry.booking.status or "").strip().lower() == "cancelled"
                    else "Confirmed"
                )
                ticket_no = entry.booking.ticket_no or ""
            elif entry.booking_id in booking_status_map:
                booking_status = booking_status_map[entry.booking_id]
                ticket_no = booking_ticket_map.get(entry.booking_id, "")

            result.append(
                {
                    "id": entry.id,
                    "txn_id": entry.txn_id or entry.id,

                    "customer_id": (
                        entry.customer_id
                        if entry.customer
                        else ""
                    ),

                    "customer_name": (
                        entry.customer.name
                        if entry.customer
                        else entry.customer_name or ""
                    ),

                    "booking_ref": booking_ref,
                    "booking_id": entry.booking_id or "",
                    "booking_status": booking_status,
                    "ticket_no": ticket_no,

                    "coupon_code": entry.coupon_code or "",

                    "type": entry.type,
                    "amount": money(entry.amount),
                    "status": entry.status,

                    "date": (
                        entry.date.isoformat()
                        if entry.date
                        else ""
                    ),
                }
            )

        return result


    # -----------------------------------------------------
    # RULES
    # -----------------------------------------------------

    if name == "rules":

        rules = Rule.objects.all().order_by("-created_at")

        return [
            {
                "id": rule.id,
                "office_id": rule.office_id or "",
                "booking_type": rule.booking_type,
                "supplier": rule.supplier or "",
                "airline": rule.airline or "",
                "fare_type": rule.fare_type,
                "flat_price": rule.flat_price or "",
                "percentage": float(rule.percentage),
                "status": rule.status,
            }
            for rule in rules
        ]


    # -----------------------------------------------------
    # SETTINGS
    # -----------------------------------------------------

    if name == "settings":

        setting = Setting.objects.filter(id=1).first()

        if not setting:
            return {}

        return {
            "min_redemption_amount": money(
                setting.min_redemption_amount
            ),

            "max_redemption_amount": money(
                setting.max_redemption_amount
            ),

            "coupon_expiry_days": setting.coupon_expiry_days,

            "allow_partial_redemption": (
                "Yes"
                if setting.allow_partial_redemption
                else "No"
            ),

            "allow_combined_offers": (
                "Yes"
                if setting.allow_combined_offers
                else "No"
            ),
        }


    return []


# =========================================================
# WRITE
# =========================================================

@transaction.atomic
def write(name, value):

    # -----------------------------------------------------
    # USERS
    # -----------------------------------------------------

    if name == "users":

        incoming_ids = set()

        for row in value or []:

            user_id = (
                row.get("id")
                or row.get("user_id")
                or new_id("USR")
            )

            incoming_ids.add(user_id)

            User.objects.update_or_create(
                user_id=user_id,
                defaults={
                    "username": row.get("username", ""),
                    "password": row.get("password", ""),
                    "name": row.get("name", ""),
                    "role": row.get("role", "USER"),
                },
            )

        User.objects.exclude(
            user_id__in=incoming_ids
        ).delete()

        return


    # -----------------------------------------------------
    # CUSTOMERS
    # -----------------------------------------------------

    if name == "customers":

        incoming_ids = set()

        for row in value or []:

            customer = get_or_create_customer(row)

            incoming_ids.add(customer.id)

        Customer.objects.exclude(
            id__in=incoming_ids
        ).delete()

        return


    # -----------------------------------------------------
    # BOOKINGS
    # -----------------------------------------------------

    if name == "bookings":

        incoming_ids = set()

        for row in value or []:

            pnr = (
                row.get("s_pnr")
                or row.get("pnr")
            )

            if not pnr:
                continue

            customer = get_or_create_customer(row)

            ticket_no = row.get("ticket_no") or None
            booking = find_booking(
                booking_id=row.get("booking_id"),
                ticket_no=ticket_no,
                pnr=pnr,
            )

            defaults = {
                    "pnr": pnr,
                    "ticket_no": ticket_no,
                    "client": customer,

                    "passenger_name": row.get(
                        "passenger_name",
                        ""
                    ),

                    "sector": row.get(
                        "sector"
                    ) or None,

                    "travel_date": date_value(
                        row.get("travel_date")
                    ),

                    "end_date": date_value(
                        row.get("end_date")
                    ),

                    "booked_date": date_value(
                        row.get("booked_date")
                    ),

                    "net_amount": decimal_value(
                        row.get("net_amount")
                    ),

                    "base_amount": decimal_value(
                        row.get("base_amount") or row.get("net_amount")
                    ),

                    "discount_percentage": decimal_value(
                        row.get("discount_percentage")
                    ),

                    "email": row.get(
                        "email"
                    ) or None,

                    "mobile": row.get(
                        "mobile"
                    ) or None,

                    "airline_pnr": row.get(
                        "airline_pnr"
                    ) or None,

                    "status": row.get(
                        "status",
                        "Confirmed"
                    ),

                    "booking_type": row.get(
                        "booking_type",
                        "Web Booking"
                    ),

                    "travel_type": row.get(
                        "travel_type",
                        "One Way"
                    ),

                    "username": row.get(
                        "username"
                    ) or None,

                    "office_id": row.get(
                        "office_id"
                    ) or None,

                    "supplier": row.get(
                        "supplier"
                    ) or None,

                    "airline": row.get(
                        "airline"
                    ) or None,

                    "fare_type": row.get(
                        "fare_type",
                        "Net Fare"
                    ),

                    "parent_pnr": row.get(
                        "parent_pnr"
                    ) or None,
                }
            if booking is None:
                booking = Booking.objects.create(**defaults)
            else:
                for field, value in defaults.items():
                    setattr(booking, field, value)
                booking.save()
            incoming_ids.add(booking.pk)

        Booking.objects.exclude(
            pk__in=incoming_ids
        ).delete()

        return


    # -----------------------------------------------------
    # COUPONS
    # -----------------------------------------------------

    if name == "coupons":

        incoming_ids = set()

        for row in value or []:

            coupon_id = (
                row.get("id")
                or row.get("coupon_code")
                or new_id("CPN")
            )

            incoming_ids.add(coupon_id)

            customer_id = row.get("customer_id")

            customer = None

            if customer_id:
                customer = Customer.objects.filter(
                    id=customer_id
                ).first()

            if not customer:
                customer = get_or_create_customer(row)

            booking_ref = row.get("booking_ref") or None
            legacy_booking_ref = row.get("booking_id")
            if not booking_ref and legacy_booking_ref and not str(legacy_booking_ref).isdigit():
                booking_ref = legacy_booking_ref
            booking = find_booking(
                booking_id=row.get("booking_id"),
                ticket_no=row.get("ticket_no"),
                pnr=booking_ref,
            )
            if booking is not None:
                booking_ref = booking_ref or booking.pnr

            Coupon.objects.update_or_create(
                id=coupon_id,
                defaults={
                    "coupon_code": row.get(
                        "coupon_code"
                    ) or coupon_id,

                    "customer": customer,

                    "booking": booking,

                    "booking_ref": booking_ref or None,

                    "customer_name": (
                        row.get("customer_name")
                        or customer.name
                    ),

                    "passenger_name": row.get(
                        "passenger_name"
                    ) or None,

                    "travel_date": date_value(
                        row.get("travel_date")
                    ),

                    "amount": decimal_value(
                        row.get("amount")
                    ),

                    "status": row.get(
                        "status",
                        "PENDING"
                    ),

                    # Critical: the existing MariaDB table has a NOT NULL
                    # `is_released` column without a DB default. Always send it.
                    "is_released": boolean_value(
                        row.get(
                            "is_released",
                            str(row.get("status", "PENDING")).upper() == "AVAILABLE"
                        )
                    ),

                    "available_date": date_value(
                        row.get("available_date")
                    ),

                    "expiry_date": date_value(
                        row.get("expiry_date")
                    ),

                    "unlock_date": date_value(
                        row.get("unlock_date")
                    ),

                    "redeemed_amount": decimal_value(
                        row.get("redeemed_amount")
                    ),
                },
            )

        Coupon.objects.exclude(
            id__in=incoming_ids
        ).delete()

        return


    # -----------------------------------------------------
    # REDEMPTIONS
    # -----------------------------------------------------

    if name == "redemptions":

        incoming_ids = set()

        for row in value or []:

            redemption_id = (
                row.get("id")
                or new_id("RDM")
            )

            incoming_ids.add(redemption_id)

            customer = None

            customer_id = row.get("customer_id")

            if customer_id:
                customer = Customer.objects.filter(
                    id=customer_id
                ).first()

            if not customer and row.get("customer_name"):

                customer = Customer.objects.filter(
                    name=row.get("customer_name")
                ).first()

            booking_ref = (
                row.get("booking_ref")
                or row.get("booking_id")
                or None
            )
            booking_record_id = row.get("booking_record_id")
            if not booking_record_id and booking_ref:
                matches = Booking.objects.filter(pnr=booking_ref)
                if matches.count() == 1:
                    booking_record_id = str(matches.first().pk)

            redemption_date = row.get("date")

            redemption_time = row.get(
                "time",
                ""
            )

            if redemption_date:

                try:
                    d = date_value(
                        redemption_date
                    )

                    if d and redemption_time:

                        dt = datetime.strptime(
                            f"{d.isoformat()} {redemption_time}",
                            "%Y-%m-%d %H:%M:%S"
                        )

                        if timezone.is_naive(dt):
                            dt = timezone.make_aware(dt)

                    elif d:

                        dt = timezone.make_aware(
                            datetime.combine(
                                d,
                                datetime.min.time()
                            )
                        )

                    else:
                        dt = timezone.now()

                except ValueError:
                    dt = timezone.now()

            else:
                dt = timezone.now()

            redemption, _ = Redemption.objects.update_or_create(
                id=redemption_id,
                defaults={
                    "customer": customer,

                    "customer_name": (
                        row.get("customer_name")
                        or (
                            customer.name
                            if customer
                            else ""
                        )
                    ),

                    "booking_id": booking_record_id or "",
                    "booking_ref": booking_ref,

                    "coupon_code": row.get(
                        "coupon_code"
                    ) or "",

                    "amount": decimal_value(
                        row.get("amount")
                    ),

                    "redeemed_amount": decimal_value(
                        row.get("redeemed_amount")
                        or row.get("amount")
                    ),

                    "status": row.get(
                        "status",
                        "SUCCESS"
                    ),

                    "redemption_type": row.get(
                        "redemption_type"
                    ) or "",

                    "date": dt,

                    "time": redemption_time,

                    "notes": row.get(
                        "notes"
                    ) or None,

                    "reversed_at": (
                        datetime_value(
                            row.get("reversed_at")
                        )
                        if row.get("reversed_at")
                        else None
                    ),

                    "reversed_amount": decimal_value(
                        row.get("reversed_amount")
                    ),
                },
            )

            # Remove old allocation rows
            RedemptionAllocation.objects.filter(
                redemption=redemption
            ).delete()

            # Create new allocation rows
            for allocation in (
                row.get("coupon_allocations")
                or []
            ):

                RedemptionAllocation.objects.create(
                    redemption=redemption,

                    coupon_code=allocation.get(
                        "coupon_code",
                        ""
                    ),

                    amount=decimal_value(
                        allocation.get("amount")
                    ),
                )

        Redemption.objects.exclude(
            id__in=incoming_ids
        ).delete()

        return


    # -----------------------------------------------------
    # LEDGER
    # -----------------------------------------------------

    if name == "ledger":

        incoming_ids = set()

        for row in value or []:

            ledger_id = (
                row.get("id")
                or row.get("txn_id")
                or new_id("TXN")
            )

            incoming_ids.add(ledger_id)

            customer = None

            customer_id = row.get("customer_id")

            if customer_id:
                customer = Customer.objects.filter(
                    id=customer_id
                ).first()

            if not customer and row.get("customer_name"):

                customer = Customer.objects.filter(
                    name=row.get("customer_name")
                ).first()

            booking_ref = row.get("booking_ref") or None
            legacy_booking_ref = row.get("booking_id")
            if not booking_ref and legacy_booking_ref and not str(legacy_booking_ref).isdigit():
                booking_ref = legacy_booking_ref
            booking = find_booking(
                booking_id=row.get("booking_id"),
                pnr=booking_ref,
            )

            Ledger.objects.update_or_create(
                id=ledger_id,
                defaults={
                    "txn_id": row.get(
                        "txn_id"
                    ) or ledger_id,

                    "customer": customer,

                    "customer_name": (
                        row.get("customer_name")
                        or (
                            customer.name
                            if customer
                            else ""
                        )
                    ),

                    "booking": booking,

                    "booking_ref": booking_ref,

                    "coupon_code": row.get(
                        "coupon_code"
                    ) or "",

                    "type": row.get(
                        "type",
                        ""
                    ),

                    "amount": decimal_value(
                        row.get("amount")
                    ),

                    "status": row.get(
                        "status",
                        "PENDING"
                    ),

                    "date": date_value(
                        row.get("date")
                    ) or timezone.localdate(),
                },
            )

        Ledger.objects.exclude(
            id__in=incoming_ids
        ).delete()

        return


    # -----------------------------------------------------
    # RULES
    # -----------------------------------------------------

    if name == "rules":

        incoming_ids = set()

        for row in value or []:

            rule_id = (
                row.get("id")
                or new_id("RULE")
            )

            incoming_ids.add(rule_id)

            Rule.objects.update_or_create(
                id=rule_id,
                defaults={
                    "office_id": row.get(
                        "office_id"
                    ) or None,

                    "booking_type": row.get(
                        "booking_type",
                        "Any Booking Type"
                    ),

                    "supplier": row.get(
                        "supplier"
                    ) or None,

                    "airline": row.get(
                        "airline"
                    ) or None,

                    "fare_type": row.get(
                        "fare_type",
                        "Any Fare Type"
                    ),

                    "flat_price": row.get(
                        "flat_price",
                        ""
                    ),

                    "percentage": decimal_value(
                        row.get("percentage")
                    ),

                    "status": row.get(
                        "status",
                        "Active"
                    ),
                },
            )

        Rule.objects.exclude(
            id__in=incoming_ids
        ).delete()

        return


    # -----------------------------------------------------
    # SETTINGS
    # -----------------------------------------------------

    if name == "settings":

        data = value or {}

        Setting.objects.update_or_create(
            id=1,
            defaults={
                "min_redemption_amount": decimal_value(
                    data.get(
                        "min_redemption_amount"
                    )
                ),

                "max_redemption_amount": decimal_value(
                    data.get(
                        "max_redemption_amount"
                    )
                ),

                "coupon_expiry_days": int(
                    data.get(
                        "coupon_expiry_days",
                        365
                    )
                ),

                "allow_partial_redemption": boolean_value(
                    data.get(
                        "allow_partial_redemption"
                    )
                ),

                "allow_combined_offers": boolean_value(
                    data.get(
                        "allow_combined_offers"
                    )
                ),
            },
        )

        return