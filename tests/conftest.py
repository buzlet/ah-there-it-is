from __future__ import annotations

from pathlib import Path
import pytest
from sqlalchemy.orm import Session

from ah_there_it_is.db.models import Base
from ah_there_it_is.db.search_schema import install_fts_schema
from ah_there_it_is.db.session import create_db_engine, create_session_factory
from tests.scale_fixture import (
    ScaleInventory,
    build_target_scale_database,
    clone_target_scale_database,
)


@pytest.fixture
def session() -> Session:
    engine = create_db_engine("sqlite://")
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        install_fts_schema(connection)
    factory = create_session_factory(engine)
    with factory() as db_session:
        yield db_session
    engine.dispose()


@pytest.fixture(scope="session")
def target_scale_template(tmp_path_factory) -> tuple[Path, ScaleInventory]:
    root = tmp_path_factory.mktemp("target-scale-template")
    path = root / "inventory.db"
    scale = build_target_scale_database(path)
    return path, scale


@pytest.fixture
def target_scale_session(
    target_scale_template: tuple[Path, ScaleInventory],
    tmp_path: Path,
):
    source, scale = target_scale_template
    database = tmp_path / "inventory.db"
    clone_target_scale_database(source, database)
    engine = create_db_engine(f"sqlite:///{database}")
    factory = create_session_factory(engine)
    try:
        with factory() as db_session:
            yield db_session, scale
    finally:
        engine.dispose()
