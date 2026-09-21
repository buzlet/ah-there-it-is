from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from ah_there_it_is.db.models import Base
from ah_there_it_is.db.search_schema import install_fts_schema
from ah_there_it_is.db.session import create_db_engine, create_session_factory


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
