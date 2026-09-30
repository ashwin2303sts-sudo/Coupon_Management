from django.db import migrations
from django.contrib.auth.hashers import make_password

def seed_admin(apps, schema_editor):
    DataStore = apps.get_model("core", "DataStore")
    DataStore.objects.get_or_create(
        name="users",
        defaults={"data": [{
            "id": "USR-001",
            "username": "admin",
            "password": make_password("admin123"),
            "name": "Super Admin",
            "role": "Super Admin",
            "status": "ACTIVE",
        }]}
    )

def reverse_seed(apps, schema_editor):
    DataStore = apps.get_model("core", "DataStore")
    DataStore.objects.filter(name="users").delete()

class Migration(migrations.Migration):
    dependencies = [("core", "0001_initial")]
    operations = [migrations.RunPython(seed_admin, reverse_seed)]
