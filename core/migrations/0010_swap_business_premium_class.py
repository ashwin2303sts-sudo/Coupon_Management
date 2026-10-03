from django.db import migrations, models
from django.db.models import Case, F, Value, When


def swap_business_and_premium(apps, schema_editor):
    database = schema_editor.connection.alias
    for model_name in ("Booking", "Rule"):
        model = apps.get_model("core", model_name)
        model.objects.using(database).update(
            fare_type=Case(
                When(fare_type="Business Class", then=Value("Premium Class")),
                When(fare_type="Premium Class", then=Value("Business Class")),
                default=F("fare_type"),
                output_field=models.CharField(max_length=50),
            )
        )


class Migration(migrations.Migration):
    dependencies = [("core", "0009_rename_middle_class_to_economy")]

    operations = [
        migrations.RunPython(swap_business_and_premium, swap_business_and_premium),
    ]
