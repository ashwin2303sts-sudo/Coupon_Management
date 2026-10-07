from django.db import migrations, models


def clear_legacy_zero_ranges(apps, schema_editor):
    Rule = apps.get_model("core", "Rule")
    Rule.objects.filter(flat_price__in=["0", "0.0", "0.00", "0.000", "0.0000"]).update(flat_price="")


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0011_rule_flat_price"),
    ]

    operations = [
        migrations.AlterField(
            model_name="rule",
            name="flat_price",
            field=models.CharField(blank=True, default="", max_length=50),
        ),
        migrations.RunPython(clear_legacy_zero_ranges, migrations.RunPython.noop),
    ]
