from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0005_coupon_booking_ref_ledger_booking_ref"),
    ]

    operations = [
        migrations.RunSQL(
            sql=(
                "ALTER TABLE coupons "
                "ADD COLUMN IF NOT EXISTS is_released TINYINT(1) NOT NULL DEFAULT 0"
            ),
            reverse_sql=(
                "ALTER TABLE coupons "
                "DROP COLUMN IF EXISTS is_released"
            ),
        ),
        migrations.SeparateDatabaseAndState(
            database_operations=[],
            state_operations=[
                migrations.AddField(
                    model_name="coupon",
                    name="is_released",
                    field=models.BooleanField(
                        db_column="is_released",
                        default=False,
                    ),
                ),
            ],
        ),
    ]
