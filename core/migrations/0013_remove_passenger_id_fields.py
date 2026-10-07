from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0012_flat_price_range"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="customer",
            name="passenger_id",
        ),
        migrations.RemoveField(
            model_name="booking",
            name="passenger_id",
        ),
    ]
