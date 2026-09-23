"""Command-line interface for local SQLite storage operations."""

from __future__ import annotations

import argparse
import json

from ah_there_it_is.config import get_settings
from ah_there_it_is.storage import (
    create_backup,
    export_portable_inventory,
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
    else:
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

    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
