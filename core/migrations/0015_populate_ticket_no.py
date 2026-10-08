"""Populate ticket_no for existing bookings that don't have one."""

import uuid

from django.db import migrations, models


def populate_ticket_no(apps, schema_editor):
    Booking = apps.get_model("core", "Booking")
    bookings_without_ticket = Booking.objects.filter(ticket_no__isnull=True)
    for booking in bookings_without_ticket:
        booking.ticket_no = f"TKT-{uuid.uuid4().hex[:8].upper()}"
        booking.save(update_fields=["ticket_no"])


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0014_booking_ticket_no"),
    ]

    operations = [
        migrations.RunPython(populate_ticket_no, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="booking",
            name="ticket_no",
            field=models.CharField(blank=True, max_length=50, null=True, unique=True),
        ),
    ]
