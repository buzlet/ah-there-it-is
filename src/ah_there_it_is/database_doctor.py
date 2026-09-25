# database_doctor.py
"""Provider-independent, read-only diagnostics for the active SQLite database."""

from __future__ import annotations

from contextlib import closing
from dataclasses import asdict, dataclass, field
import heapq
from pathlib import Path
import sqlite3
from typing import Any, Iterable, Literal

from ah_there_it_is.db.migrations import migration_heads
from ah_there_it_is.db.search_consistency import expected_fts_objects, search_consistency
from ah_there_it_is.db.search_schema import drop_fts_schema, install_fts_schema, rebuild_fts_index
from ah_there_it_is.domain.names import normalize_name
from ah_there_it_is.domain.states import ItemState, LocationStatus
from ah_there_it_is.storage import sqlite_path_from_url

_SAMPLE_LIMIT = 20
_TABLES = ('categories', 'locations', 'items', 'aliases', 'tags', 'item_tags', 'events')


@dataclass(frozen=True)
class DoctorCheck:
    status: Literal['ok', 'warning', 'error']
    count: int = 0
    samples: tuple[str, ...] = ()
    detail: str | None = None


@dataclass
class DoctorReport:
    database_path: str | None = None
    database_heads: tuple[str, ...] = ()
    packaged_heads: tuple[str, ...] = ()
    counts: dict[str, int] = field(default_factory=dict)
    checks: dict[str, DoctorCheck] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return bool(self.checks) and all(c.status != 'error' for c in self.checks.values())

    def as_dict(self) -> dict[str, Any]:
        return {
            'ok': self.ok,
            'database_path': self.database_path,
            'database_heads': self.database_heads,
            'packaged_heads': self.packaged_heads,
            'counts': self.counts,
            'checks': {name: asdict(check) for name, check in self.checks.items()},
        }


def _check(report: DoctorReport, name: str, samples: tuple[str, ...] = (), *, count: int | None = None, warning: bool = False, detail: str | None = None) -> None:
    total = len(samples) if count is None else count
    report.checks[name] = DoctorCheck(
        'warning' if warning and total else 'error' if total else 'ok',
        total,
        samples[:_SAMPLE_LIMIT],
        detail,
    )


def _bounded_rows(rows: Iterable[sqlite3.Row | tuple[Any, ...]], *, skip_ok: bool = False) -> tuple[int, tuple[str, ...]]:
    """Count a result stream while retaining only deterministic diagnostic samples."""
    count = 0
    samples: list[str] = []
    for row in rows:
        if skip_ok and len(row) == 1 and row[0] == 'ok':
            continue
        count += 1
        if len(samples) < _SAMPLE_LIMIT:
            samples.append(str(row[0]) if len(row) == 1 else str(tuple(row)))
    return count, tuple(samples)


def _sql_violation_summary(
    connection: sqlite3.Connection,
    query: str,
    parameters: tuple[Any, ...] = (),
) -> tuple[int, tuple[str, ...]]:
    """Return an exact count and bounded, ID-ordered samples for a violation query."""
    count = int(connection.execute(f'SELECT count(*) FROM ({query})', parameters).fetchone()[0])
    rows = connection.execute(
        f'SELECT id FROM ({query}) ORDER BY id LIMIT ?',
        (*parameters, _SAMPLE_LIMIT),
    )
    return count, tuple(str(row[0]) for row in rows)


def _sql_check(
    connection: sqlite3.Connection,
    report: DoctorReport,
    name: str,
    query: str,
    parameters: tuple[Any, ...] = (),
    *,
    warning: bool = False,
) -> None:
    count, samples = _sql_violation_summary(connection, query, parameters)
    _check(report, name, samples, count=count, warning=warning)


def _doctor_normalize_name(value: object) -> str:
    return normalize_name(value) if isinstance(value, str) else ''


def _register_doctor_functions(connection: sqlite3.Connection) -> None:
    connection.create_function('doctor_normalize_name', 1, _doctor_normalize_name, deterministic=True)


def diagnose_database(database_url: str) -> DoctorReport:
    report = DoctorReport()
    try:
        database = sqlite_path_from_url(database_url)
    except Exception:
        _check(report, 'database', ('unsupported SQLite URL',), detail='configured database must be file-backed SQLite')
        return report
    report.database_path = str(database)
    if not database.is_file():
        _check(report, 'database', ('missing',), detail='configured database file does not exist')
        return report
    try:
        report.packaged_heads = tuple(sorted(migration_heads()))
    except Exception:
        _check(report, 'schema', ('packaged migrations unavailable',))
        return report
    wal = Path(str(database) + '-wal')
    if wal.exists() and not Path(str(database) + '-shm').exists():
        _check(report, 'database', ('WAL shared memory unavailable',), detail='read-only inspection cannot create a WAL sidecar')
        return report
    try:
        # SQLite mode=ro can create WAL sidecars. Immutable is safe only when no WAL exists.
        wal_present = wal.exists()
        uri = database.as_uri() + ('?mode=ro' if wal_present else '?mode=ro&immutable=1')
        with closing(sqlite3.connect(uri, uri=True)) as connection:
            connection.execute('PRAGMA query_only=ON')
            _register_doctor_functions(connection)
            connection.execute('BEGIN')
            _inspect(connection, report)
        if not wal_present and wal.exists():
            _check(report, 'database', ('database changed during inspection',))
    except (sqlite3.Error, OSError) as exc:
        _check(report, 'database', ('unreadable',), detail=str(exc))
    return report


def _inspect(connection: sqlite3.Connection, report: DoctorReport) -> None:
    integrity_count, integrity_samples = _bounded_rows(connection.execute('PRAGMA integrity_check'), skip_ok=True)
    _check(report, 'integrity', integrity_samples, count=integrity_count)
    foreign_key_count, foreign_key_samples = _bounded_rows(connection.execute('PRAGMA foreign_key_check'))
    _check(report, 'foreign_keys', foreign_key_samples, count=foreign_key_count)
    try:
        report.database_heads = tuple(sorted(str(row[0]) for row in connection.execute('SELECT version_num FROM alembic_version')))
    except sqlite3.Error:
        report.database_heads = ()
    _check(report, 'schema', () if report.database_heads == report.packaged_heads and report.packaged_heads else ('revision mismatch',), detail=f'database={report.database_heads!r}; packaged={report.packaged_heads!r}')
    if report.checks['integrity'].status == 'error' or report.checks['schema'].status == 'error':
        return
    for table in _TABLES:
        report.counts[table] = int(connection.execute(f'SELECT count(*) FROM {table}').fetchone()[0])
    _inspect_identity(connection, report)
    _inspect_scalars(connection, report)
    _inspect_fts(connection, report)


def _inspect_identity(connection: sqlite3.Connection, report: DoctorReport) -> None:
    for table, owner in (('categories', 'parent_id'), ('locations', 'parent_id'), ('items', 'category_id'), ('aliases', 'item_id'), ('tags', None)):
        normalized = 'doctor_normalize_name(name)'
        _sql_check(
            connection,
            report,
            f'{table}_normalized_names',
            f'SELECT id FROM {table} WHERE normalized_name IS NOT {normalized}',
        )
        _sql_check(
            connection,
            report,
            f'{table}_nonblank_names',
            f"SELECT id FROM {table} WHERE {normalized} = ''",
        )
        partition = f'{owner}, {normalized}' if owner else normalized
        _sql_check(
            connection,
            report,
            f'{table}_duplicate_identity',
            f'SELECT id FROM ('
            f'SELECT id, row_number() OVER (PARTITION BY {partition} ORDER BY id) AS occurrence '
            f'FROM {table}) WHERE occurrence > 1',
            warning=table == 'items',
        )
    for table in ('categories', 'locations'):
        parents = {int(row[0]): row[1] for row in connection.execute(f'SELECT id, parent_id FROM {table}')}
        cycles: set[int] = set()
        done: set[int] = set()
        for start in sorted(parents):
            trail: dict[int, int] = {}
            node: int | None = start
            while node is not None and node in parents and node not in done:
                if node in trail:
                    cycles.update(list(trail)[trail[node]:])
                    break
                trail[node] = len(trail)
                node = parents[node]
            done.update(trail)
        samples = tuple(str(value) for value in heapq.nsmallest(_SAMPLE_LIMIT, cycles))
        _check(report, f'{table}_cycles', samples, count=len(cycles))


def _inspect_scalars(connection: sqlite3.Connection, report: DoctorReport) -> None:
    allowed = tuple(state.value for state in ItemState)
    allowed_locations = tuple(status.value for status in LocationStatus)
    terminal_states = (ItemState.REMOVED.value,)
    _sql_check(
        connection,
        report,
        'item_states',
        f"SELECT id FROM items WHERE state IS NULL OR state NOT IN ({','.join('?' for _ in allowed)})",
        allowed,
    )
    _sql_check(
        connection,
        report,
        'item_quantities',
        "SELECT id FROM items WHERE quantity_mode NOT IN ('exact', 'approximate', 'unknown') "
        "OR (quantity_mode = 'unknown') != (quantity IS NULL) "
        "OR (quantity IS NOT NULL AND (typeof(quantity) != 'integer' OR quantity < 1))",
    )
    _sql_check(
        connection,
        report,
        'item_location_truth',
        f"SELECT id FROM items WHERE location_status IS NULL OR location_status NOT IN ({','.join('?' for _ in allowed_locations)}) "
        "OR (location_status = ?) != (current_location_id IS NOT NULL) "
        f"OR (state IN ({','.join('?' for _ in terminal_states)})) != (location_status = ?)",
        (*allowed_locations, LocationStatus.KNOWN.value, *terminal_states, LocationStatus.NOT_APPLICABLE.value),
    )
    _sql_check(
        connection,
        report,
        'item_removal_truth',
        "SELECT id FROM items WHERE (state = 'removed') != (removal_reason IS NOT NULL) "
        "OR (removal_reason IS NOT NULL AND trim(removal_reason) = '')",
    )


def _inspect_fts(connection: sqlite3.Connection, report: DoctorReport) -> None:
    missing = expected_fts_objects(connection)
    _check(report, 'fts_schema', missing)
    if missing:
        return
    try:
        result = search_consistency(connection)
        for name in ('missing', 'mismatched', 'extra'):
            samples = tuple(str(i) for i in getattr(result, f'{name}_ids'))
            _check(report, f'fts_{name}_rows', samples, count=getattr(result, f'{name}_count'))
    except sqlite3.Error as exc:
        _check(report, 'fts_content', ('unreadable',), detail=str(exc))


def repair_search_index(database_url: str) -> DoctorReport:
    """Explicitly replace only derived FTS objects after base checks pass."""
    before = diagnose_database(database_url)
    if not before.database_path or any(check.status == 'error' for name, check in before.checks.items() if not name.startswith('fts_')):
        _check(before, 'repair', ('base invariants unhealthy',))
        return before
    database = Path(before.database_path)
    try:
        with closing(sqlite3.connect(database.as_uri() + '?mode=rw', uri=True)) as connection, connection:
            connection.execute('PRAGMA foreign_keys=ON')
            _register_doctor_functions(connection)
            connection.execute('BEGIN IMMEDIATE')
            locked = DoctorReport(database_path=before.database_path, packaged_heads=before.packaged_heads)
            _inspect(connection, locked)
            if any(check.status == 'error' for name, check in locked.checks.items() if not name.startswith('fts_')):
                connection.rollback()
                _check(locked, 'repair', ('base invariants unhealthy',))
                return locked
            drop_fts_schema(connection)
            install_fts_schema(connection)
            rebuild_fts_index(connection)
            connection.commit()
    except (sqlite3.Error, OSError) as exc:
        _check(before, 'repair', ('failed',), detail=str(exc))
        return before
    return diagnose_database(database_url)
