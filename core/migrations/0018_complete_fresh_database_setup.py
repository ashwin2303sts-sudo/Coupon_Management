from django.contrib.auth.hashers import make_password
from django.db import migrations


def ensure_initial_admin_and_allocation_table(apps, schema_editor):
    User = apps.get_model("core", "User")
    User.objects.get_or_create(
        username="admin",
        defaults={
            "user_id": "USR-001",
            "password": make_password("admin123"),
            "name": "Super Admin",
            "role": "Super Admin",
        },
    )

    RedemptionAllocation = apps.get_model("core", "RedemptionAllocation")
    table_name = RedemptionAllocation._meta.db_table
    existing_tables = schema_editor.connection.introspection.table_names()
    if table_name not in existing_tables:
        schema_editor.create_model(RedemptionAllocation)


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0017_booking_import_mode"),
    ]

    operations = [
        migrations.RunPython(
            ensure_initial_admin_and_allocation_table,
            migrations.RunPython.noop,
        ),
    ]
