from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("core", "0007_coupon_is_released_db_default")]

    operations = [
        migrations.AddField(
            model_name="booking",
            name="base_amount",
            field=models.DecimalField(decimal_places=2, default=0, max_digits=12),
        ),
        migrations.AddField(
            model_name="booking",
            name="discount_percentage",
            field=models.DecimalField(decimal_places=4, default=0, max_digits=7),
        ),
    ]
