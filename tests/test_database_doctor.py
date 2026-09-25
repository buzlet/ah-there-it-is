# test_database_doctor.py
from __future__ import annotations

from contextlib import closing
import json
from pathlib import Path
import sqlite3

import pytest
from sqlalchemy.orm import Session

from ah_there_it_is.config import Settings
from ah_there_it_is.database_doctor import diagnose_database, repair_search_index
from ah_there_it_is.db.migrations import upgrade_database
from ah_there_it_is.db.session import create_db_engine
from ah_there_it_is.runtime_cli import main
from ah_there_it_is.services.inventory import InventoryService
from tests.scale_fixture import build_target_scale_inventory


@pytest.fixture
def active(tmp_path: Path) -> tuple[Path, str]:
    path = tmp_path / 'active.db'
    url = f'sqlite:///{path}'
    upgrade_database(url)
    engine = create_db_engine(url)
    with Session(engine) as session:
        inventory = InventoryService(session, autocommit=False)
        category = inventory.create_category('Electronics')
        location = inventory.create_location('Office')
        inventory.create_item('CH341A', category_id=category.id, location_id=location.id,
                              aliases=['Programmer'], tags=['Tools'], attributes={'model': 'A'},
                              description='USB programmer')
        inventory.create_item('CH341A', category_id=category.id, allow_duplicate=True)
        session.commit()
    engine.dispose()
    return path, url


def _sql(path: Path, statement: str, parameters: tuple = ()) -> None:
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute("PRAGMA ignore_check_constraints=ON")
        connection.execute(statement, parameters)


def _snapshot(path: Path) -> dict[str, list[tuple]]:
    with closing(sqlite3.connect(path)) as connection:
        names = [row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'item_search_fts%' AND name NOT LIKE 'sqlite_%'"
        )]
        return {name: list(connection.execute(f'SELECT * FROM {name} ORDER BY rowid')) for name in names}


def test_healthy_and_allowed_duplicate_warning(active: tuple[Path, str]) -> None:
    _, url = active
    report = diagnose_database(url)
    assert report.ok
    assert report.counts['items'] == 2
    assert report.checks['items_duplicate_identity'].status == 'warning'
    assert report.checks['items_duplicate_identity'].count == 1


def test_doctor_is_read_only_for_normalized_corruption(active: tuple[Path, str]) -> None:
    path, url = active
    _sql(path, "UPDATE items SET normalized_name='wrong' WHERE id=1")
    before = {p.name: p.read_bytes() for p in path.parent.glob('active.db*')}
    report = diagnose_database(url)
    after = {p.name: p.read_bytes() for p in path.parent.glob('active.db*')}
    assert not report.ok
    assert report.checks['items_normalized_names'].status == 'error'
    assert after.keys() == before.keys()
    assert all(after[name] == contents for name, contents in before.items() if not name.endswith('-shm'))
    assert not repair_search_index(url).ok
    with sqlite3.connect(path) as connection:
        assert connection.execute('SELECT normalized_name FROM items WHERE id=1').fetchone()[0] == 'wrong'


def test_cycles_states_quantities_and_root_identity(active: tuple[Path, str]) -> None:
    path, url = active
    _sql(path, "INSERT INTO categories (id,parent_id,name,normalized_name,created_at,updated_at) VALUES (10,NULL,'Electronics','electronics','2026','2026')")
    _sql(path, "UPDATE categories SET parent_id=10 WHERE id=1")
    _sql(path, "UPDATE categories SET parent_id=1 WHERE id=10")
    _sql(path, "INSERT INTO locations (id,parent_id,name,normalized_name,created_at,updated_at) VALUES (10,NULL,'Office','office','2026','2026')")
    _sql(path, "UPDATE locations SET parent_id=10 WHERE id=1")
    _sql(path, "UPDATE locations SET parent_id=1 WHERE id=10")
    _sql(path, "UPDATE items SET state='invalid', quantity=0 WHERE id=1")
    report = diagnose_database(url)
    assert not report.ok
    assert report.checks['categories_cycles'].count == 2
    assert report.checks['locations_cycles'].count == 2
    assert report.checks['item_states'].count == 1
    assert report.checks['item_quantities'].count == 1


@pytest.mark.parametrize('corruption,check', [
    ("DELETE FROM item_search_fts WHERE rowid=1", 'fts_missing_rows'),
    ("UPDATE item_search_fts SET name='wrong' WHERE rowid=1", 'fts_mismatched_rows'),
    ("INSERT INTO item_search_fts(rowid,name) VALUES (999,'extra')", 'fts_extra_rows'),
    ("DROP TRIGGER item_search_items_ai", 'fts_schema'),
])
def test_fts_corruption_is_read_only_and_repairable(active: tuple[Path, str], corruption: str, check: str) -> None:
    path, url = active
    _sql(path, corruption)
    authoritative = _snapshot(path)
    before = {p.name: p.read_bytes() for p in path.parent.glob('active.db*')}
    report = diagnose_database(url)
    assert not report.ok
    assert report.checks[check].status == 'error'
    after = {p.name: p.read_bytes() for p in path.parent.glob('active.db*')}
    assert after.keys() == before.keys()
    assert all(after[name] == contents for name, contents in before.items() if not name.endswith('-shm'))
    assert repair_search_index(url).ok
    assert _snapshot(path) == authoritative
    assert repair_search_index(url).ok
    assert _snapshot(path) == authoritative


def test_missing_and_outdated_database_not_created_or_upgraded(tmp_path: Path, active: tuple[Path, str]) -> None:
    missing = tmp_path / 'absent' / 'inventory.db'
    assert not diagnose_database(f'sqlite:///{missing}').ok
    assert not repair_search_index(f'sqlite:///{missing}').ok
    assert not missing.parent.exists()
    path, url = active
    _sql(path, "UPDATE alembic_version SET version_num='old'")
    before = path.read_bytes()
    assert not diagnose_database(url).ok
    assert not repair_search_index(url).ok
    assert path.read_bytes() == before


def test_cli_json_exit_status(active: tuple[Path, str], monkeypatch, capsys) -> None:
    from ah_there_it_is import runtime_cli
    path, url = active
    monkeypatch.setattr(runtime_cli, 'get_settings', lambda: Settings(database_url=url))
    assert main(['doctor']) == 0
    assert json.loads(capsys.readouterr().out)['ok']
    _sql(path, 'DELETE FROM item_search_fts WHERE rowid=1')
    assert main(['doctor']) == 2
    assert not json.loads(capsys.readouterr().out)['ok']
    assert main(['repair-search-index']) == 0
    assert json.loads(capsys.readouterr().out)['ok']


def test_target_scale_inventory(tmp_path: Path) -> None:
    path = tmp_path / 'scale.db'
    url = f'sqlite:///{path}'
    upgrade_database(url)
    engine = create_db_engine(url)
    with Session(engine) as session:
        build_target_scale_inventory(session)
    engine.dispose()
    report = diagnose_database(url)
    assert report.ok
    assert report.counts['items'] == 1000
    assert report.checks['fts_mismatched_rows'].count == 0


def test_root_duplicates_and_blank_names(active: tuple[Path, str]) -> None:
    path, url = active
    for table, name in (('categories', 'Electronics'), ('locations', 'Office')):
        _sql(path, f"INSERT INTO {table} (id,parent_id,name,normalized_name,created_at,updated_at) VALUES (10,NULL,? ,?,'2026','2026')", (name, name.casefold()))
    _sql(path, "UPDATE aliases SET name='   ', normalized_name='' WHERE id=1")
    report = diagnose_database(url)
    assert not report.ok
    assert report.checks['categories_duplicate_identity'].count == 1
    assert report.checks['locations_duplicate_identity'].count == 1
    assert report.checks['aliases_nonblank_names'].count == 1


def test_modified_trigger_definition_is_detected(active: tuple[Path, str]) -> None:
    path, url = active
    _sql(path, 'DROP TRIGGER item_search_items_ai')
    _sql(path, 'CREATE TRIGGER item_search_items_ai AFTER INSERT ON items BEGIN SELECT 1; END')
    assert diagnose_database(url).checks['fts_schema'].status == 'error'
    assert repair_search_index(url).ok


def test_portable_import_uses_shared_search_consistency(tmp_path: Path, monkeypatch) -> None:
    from ah_there_it_is import storage
    from ah_there_it_is.db import search_consistency as boundary
    fixture = Path('tests/fixtures/inventory-portable-v1.json').resolve()
    active = tmp_path / 'active.db'
    upgrade_database(f'sqlite:///{active}')
    called = []
    original = boundary.search_consistency

    def checked(connection):
        result = original(connection)
        called.append(result)
        return result

    monkeypatch.setattr(boundary, 'search_consistency', checked)
    imported = tmp_path / 'imported.db'
    storage.import_portable_inventory(f'sqlite:///{active}', fixture, imported)
    assert len(called) == 1 and called[0].ok
    assert diagnose_database(f'sqlite:///{imported}').ok


def test_foreign_key_violation_blocks_repair(active: tuple[Path, str]) -> None:
    path, url = active
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute('PRAGMA foreign_keys=OFF')
        connection.execute('UPDATE items SET category_id=999 WHERE id=1')
    before = _snapshot(path)
    report = diagnose_database(url)
    assert not report.ok
    assert report.checks['foreign_keys'].count == 1
    assert not repair_search_index(url).ok
    assert _snapshot(path) == before


def test_doctor_reads_uncheckpointed_wal_without_checkpoint(active: tuple[Path, str]) -> None:
    path, url = active
    with closing(sqlite3.connect(path)) as writer:
        writer.execute('PRAGMA journal_mode=WAL')
        writer.execute("INSERT INTO items (name,normalized_name,state,quantity,attributes,created_at,updated_at) VALUES ('WAL Item','wal item','unknown',1,'{}','2026','2026')")
        writer.commit()
        wal = Path(str(path) + '-wal')
        assert wal.exists()
        before = (path.read_bytes(), wal.read_bytes())
        report = diagnose_database(url)
        assert report.ok
        assert report.counts['items'] == 3
        assert (path.read_bytes(), wal.read_bytes()) == before


def test_null_category_duplicate_is_warning(active: tuple[Path, str]) -> None:
    path, url = active
    _sql(path, "INSERT INTO items (name,normalized_name,state,quantity,attributes,created_at,updated_at) VALUES ('Uncategorized','uncategorized','unknown',1,'{}','2026','2026')")
    _sql(path, "INSERT INTO items (name,normalized_name,state,quantity,attributes,created_at,updated_at) VALUES ('Uncategorized','uncategorized','unknown',1,'{}','2026','2026')")
    report = diagnose_database(url)
    assert report.ok
    assert report.checks['items_duplicate_identity'].status == 'warning'
    assert report.checks['items_duplicate_identity'].count == 2


def test_fts_diagnostic_samples_are_bounded(active: tuple[Path, str]) -> None:
    path, url = active
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.executemany(
            "INSERT INTO item_search_fts(rowid,name) VALUES (?, 'extra')",
            [(1000 + index,) for index in range(25)],
        )
    report = diagnose_database(url)
    assert not report.ok
    assert report.checks['fts_extra_rows'].count == 25
    assert len(report.checks['fts_extra_rows'].samples) == 20


def test_thousands_of_violations_have_exact_counts_and_bounded_samples(
    active: tuple[Path, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from ah_there_it_is import database_doctor

    path, url = active
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute("PRAGMA ignore_check_constraints=ON")
        connection.execute(
            """
            WITH RECURSIVE ids(id) AS (
                VALUES (1000)
                UNION ALL
                SELECT id + 1 FROM ids WHERE id < 3499
            )
            INSERT INTO items (
                id, name, normalized_name, state, quantity, current_location_id,
                location_status, attributes, created_at, updated_at
            )
            SELECT id, '   ', 'wrong', 'invalid', 0, NULL, 'unknown', '{}', '2026', '2026'
            FROM ids
            """
        )
        update_trigger = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type='trigger' AND name='items_location_truth_bu'"
        ).fetchone()[0]
        connection.execute('DROP TRIGGER items_location_truth_bu')
        connection.execute("UPDATE items SET location_status='invalid' WHERE id >= 1000")
        connection.execute(update_trigger)
        connection.execute('DELETE FROM item_search_fts WHERE rowid >= 1000')

    helper_results: list[tuple[int, tuple[str, ...]]] = []
    original = database_doctor._sql_violation_summary

    def checked_summary(connection, query, parameters=()):
        result = original(connection, query, parameters)
        assert isinstance(result[1], tuple)
        assert len(result[1]) <= 20
        helper_results.append(result)
        return result

    monkeypatch.setattr(database_doctor, '_sql_violation_summary', checked_summary)
    authoritative = _snapshot(path)
    before = {candidate.name: candidate.read_bytes() for candidate in path.parent.glob('active.db*')}
    report = diagnose_database(url)
    after = {candidate.name: candidate.read_bytes() for candidate in path.parent.glob('active.db*')}

    expected = tuple(str(value) for value in range(1000, 1020))
    for name in (
        'items_normalized_names',
        'items_nonblank_names',
        'item_states',
        'item_quantities',
        'item_location_truth',
        'fts_missing_rows',
    ):
        assert report.checks[name].count == 2500
        assert report.checks[name].samples == expected
    assert report.checks['items_duplicate_identity'].count == 2500
    assert report.checks['items_duplicate_identity'].samples == ('2',) + tuple(
        str(value) for value in range(1001, 1020)
    )
    assert helper_results
    assert all(len(check.samples) <= 20 for check in report.checks.values())
    assert after.keys() == before.keys()
    assert all(after[name] == contents for name, contents in before.items() if not name.endswith('-shm'))
    assert _snapshot(path) == authoritative
