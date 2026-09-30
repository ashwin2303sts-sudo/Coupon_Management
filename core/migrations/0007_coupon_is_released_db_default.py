from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0006_coupon_is_released"),
    ]

    operations = [
        migrations.RunSQL(
            sql=(
                "ALTER TABLE coupons "
                "MODIFY COLUMN is_released TINYINT(1) NOT NULL DEFAULT 0"
            ),
            reverse_sql=(
                "ALTER TABLE coupons "
                "MODIFY COLUMN is_released TINYINT(1) NOT NULL"
            ),
        ),
        migrations.AlterField(
            model_name="coupon",
            name="is_released",
            field=models.BooleanField(
                db_column="is_released",
                db_default=False,
                default=False,
            ),
        ),
    ]
