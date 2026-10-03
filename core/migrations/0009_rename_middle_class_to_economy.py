from django.db import migrations


def rename_middle_class(apps, schema_editor):
    Booking = apps.get_model("core", "Booking")
    Rule = apps.get_model("core", "Rule")
    Booking.objects.using(schema_editor.connection.alias).filter(
        fare_type="Middle Class"
    ).update(fare_type="Economy Class")
    Rule.objects.using(schema_editor.connection.alias).filter(
        fare_type="Middle Class"
    ).update(fare_type="Economy Class")


class Migration(migrations.Migration):
    dependencies = [("core", "0008_booking_base_amount_discount")]

    operations = [
        migrations.RunPython(rename_middle_class, migrations.RunPython.noop),
    ]
