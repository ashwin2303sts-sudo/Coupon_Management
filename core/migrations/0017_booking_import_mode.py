from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0016_booking_unique_id_allow_duplicate_pnr"),
    ]

    operations = [
        migrations.AddField(
            model_name="booking",
            name="is_auto",
            field=models.BooleanField(db_column="auto", default=False),
        ),
        migrations.AddField(
            model_name="booking",
            name="is_manual",
            field=models.BooleanField(db_column="manual", default=False),
        ),
        migrations.AlterField(
            model_name="booking",
            name="status",
            field=models.CharField(
                choices=[("Confirmed", "Confirmed"), ("Cancelled", "Cancelled")],
                default="Confirmed",
                max_length=30,
            ),
        ),
    ]
