from django.db import migrations, models


def update_check_constraint(apps, schema_editor):
    connection = schema_editor.connection
    with connection.cursor() as cursor:
        try:
            cursor.execute("ALTER TABLE bookings DROP CONSTRAINT chk_booking_status")
        except Exception:
            try:
                cursor.execute("ALTER TABLE bookings DROP CHECK chk_booking_status")
            except Exception:
                pass
        try:
            cursor.execute("ALTER TABLE bookings ADD CONSTRAINT chk_booking_status CHECK (status IN ('Confirmed', 'Cancelled', 'Rescheduled'))")
        except Exception:
            pass


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0019_alter_booking_id'),
    ]

    operations = [
        migrations.AlterField(
            model_name='booking',
            name='status',
            field=models.CharField(
                choices=[('Confirmed', 'Confirmed'), ('Cancelled', 'Cancelled'), ('Rescheduled', 'Rescheduled')],
                default='Confirmed',
                max_length=30
            ),
        ),
        migrations.RunPython(update_check_constraint, reverse_code=migrations.RunPython.noop),
    ]
