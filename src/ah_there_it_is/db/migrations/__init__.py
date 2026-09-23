"""Packaged Alembic migration configuration and runner."""

from __future__ import annotations

from contextlib import contextmanager
from importlib.resources import as_file, files
from typing import Iterator

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory


@contextmanager
def migration_config(database_url: str) -> Iterator[Config]:
    """Build Alembic config from packaged resources for one explicit target."""
    resource_root = files(__package__)
    with as_file(resource_root) as script_location:
        config = Config()
        config.set_main_option("script_location", str(script_location))
        config.set_main_option("sqlalchemy.url", database_url)
        config.attributes["database_url_override"] = database_url
        yield config


def migration_heads() -> tuple[str, ...]:
    with migration_config("sqlite://") as config:
        return tuple(ScriptDirectory.from_config(config).get_heads())


def upgrade_database(database_url: str, revision: str = "head") -> None:
    """Explicitly upgrade one database using the packaged migration history."""
    with migration_config(database_url) as config:
        command.upgrade(config, revision)


def downgrade_database(database_url: str, revision: str = "base") -> None:
    with migration_config(database_url) as config:
        command.downgrade(config, revision)


def check_database_schema(database_url: str) -> None:
    """Fail when model metadata would require a new migration."""
    with migration_config(database_url) as config:
        command.check(config)
