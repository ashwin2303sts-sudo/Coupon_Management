import json
from pathlib import Path
from django.core.management.base import BaseCommand
from core.storage import write

class Command(BaseCommand):
    help = "Import the existing JSON data folder into MySQL."

    def add_arguments(self, parser):
        parser.add_argument("--path", default="legacy_json_backup", help="Path to the legacy JSON data folder.")

    def handle(self, *args, **options):
        data_dir = Path(options["path"])
        if not data_dir.exists():
            self.stderr.write(self.style.ERROR(f"Folder not found: {data_dir}"))
            return
        count = 0
        for path in sorted(data_dir.glob("*.json")):
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
                write(path.stem, value)
                count += 1
                self.stdout.write(self.style.SUCCESS(f"Imported {path.name}"))
            except Exception as exc:
                self.stderr.write(self.style.ERROR(f"Failed {path.name}: {exc}"))
        self.stdout.write(self.style.SUCCESS(f"Imported {count} JSON dataset(s) into MySQL."))
