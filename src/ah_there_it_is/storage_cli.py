"""Command-line maintenance for the local SQLite store."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ah_there_it_is.config import get_settings
from ah_there_it_is.storage_ops import (
    backup_database,
    export_portable_json,
    restore_database,
    validate_database_file,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    backup = subparsers.add_parser("backup")
    backup.add_argument("destination")

    validate = subparsers.add_parser("validate")
    validate.add_argument("database")

    restore = subparsers.add_parser("restore")
    restore.add_argument("candidate")
    restore.add_argument("--rollback-backup")
    restore.add_argument("--confirm-app-stopped", action="store_true")

    export = subparsers.add_parser("export")
    export.add_argument("output")
    export.add_argument("--include-evaluations", action="store_true")

    args = parser.parse_args()
    database_url = get_settings().database_url

    if args.command == "backup":
        result = backup_database(database_url, args.destination).as_dict()
    elif args.command == "validate":
        result = validate_database_file(args.database).as_dict()
    elif args.command == "restore":
        result = restore_database(
            database_url,
            args.candidate,
            confirm_app_stopped=args.confirm_app_stopped,
            rollback_backup=args.rollback_backup,
        ).as_dict()
    else:
        document = export_portable_json(
            database_url,
            include_evaluations=args.include_evaluations,
        )
        output = Path(args.output).expanduser()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(document, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        result = {
            "output": str(output.resolve()),
            "format": document["format"],
            "schema_revision": document["schema_revision"],
            "evaluation_included": document["evaluation_included"],
        }

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
