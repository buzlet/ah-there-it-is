"""Command-line interface for local SQLite storage operations."""

from __future__ import annotations

import argparse
import json

from ah_there_it_is.config import get_settings
from ah_there_it_is.db.migrations import check_database_schema, upgrade_database
from ah_there_it_is.storage import (
    create_backup,
    export_portable_inventory,
    import_portable_inventory,
    validate_portable_import_target,
    validate_portable_inventory,
    restore_backup,
    validate_database,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    backup = subparsers.add_parser("backup")
    backup.add_argument("destination")
    backup.add_argument("--overwrite", action="store_true")

    validate = subparsers.add_parser("validate")
    validate.add_argument("database")

    restore = subparsers.add_parser("restore")
    restore.add_argument("candidate")
    restore.add_argument("--safety-backup")

    export = subparsers.add_parser("export-json")
    export.add_argument("destination")

    subparsers.add_parser("upgrade")
    subparsers.add_parser("migration-check")

    import_json = subparsers.add_parser("import-json")
    import_json.add_argument("source")
    import_json.add_argument("destination")
    import_json.add_argument("--dry-run", action="store_true")

    args = parser.parse_args()
    database_url = get_settings().database_url

    if args.command == "backup":
        result = create_backup(
            database_url,
            args.destination,
            overwrite=args.overwrite,
        ).as_dict()
    elif args.command == "validate":
        result = validate_database(args.database).as_dict()
    elif args.command == "restore":
        result = restore_backup(
            database_url,
            args.candidate,
            safety_backup=args.safety_backup,
        ).as_dict()
    elif args.command == "upgrade":
        upgrade_database(database_url)
        result = {"upgraded_to": "head"}
    elif args.command == "migration-check":
        check_database_schema(database_url)
        result = {"migration_check": "ok"}
    elif args.command == "export-json":
        document = export_portable_inventory(database_url, args.destination)
        result = {
            "destination": args.destination,
            "format": document["format"],
            "alembic_revision": document["source"]["alembic_revision"],
            "categories": len(document["inventory"]["categories"]),
            "locations": len(document["inventory"]["locations"]),
            "items": len(document["inventory"]["items"]),
            "events": len(document["history"]["events"]),
        }
    elif args.dry_run:
        document = validate_portable_inventory(args.source)
        target = validate_portable_import_target(database_url, args.destination)
        result = {
            "dry_run": True,
            "source": args.source,
            "destination": str(target),
            "format": document.format,
            "source_alembic_revision": document.source.alembic_revision,
            "categories": len(document.inventory.categories),
            "locations": len(document.inventory.locations),
            "items": len(document.inventory.items),
            "events": len(document.history.events),
        }
    else:
        result = import_portable_inventory(
            database_url,
            args.source,
            args.destination,
        ).as_dict()

    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
