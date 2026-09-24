from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest

from ah_there_it_is.app import create_app
from ah_there_it_is.config import Settings, get_settings, resolve_database_url
from ah_there_it_is.data_paths import (
    default_database_path,
    default_database_url,
    resolve_data_dir,
)
from ah_there_it_is.storage import CURRENT_SCHEMA_REVISION, validate_database
from ah_there_it_is.storage_cli import main as storage_cli_main


def test_linux_xdg_data_home_and_fallback(tmp_path: Path) -> None:
    home = tmp_path / "home"
    xdg = tmp_path / "xdg"

    assert resolve_data_dir(
        environ={"XDG_DATA_HOME": str(xdg)},
        platform_name="linux",
        home=home,
    ) == (xdg / "ah-there-it-is").resolve()

    assert resolve_data_dir(
        environ={},
        platform_name="linux",
        home=home,
    ) == (home / ".local" / "share" / "ah-there-it-is").resolve()

    assert resolve_data_dir(
        environ={"XDG_DATA_HOME": "   "},
        platform_name="linux",
        home=home,
    ) == (home / ".local" / "share" / "ah-there-it-is").resolve()


def test_macos_data_home(tmp_path: Path) -> None:
    home = tmp_path / "home"

    assert resolve_data_dir(
        environ={},
        platform_name="darwin",
        home=home,
    ) == (home / "Library" / "Application Support" / "AhThereItIs").resolve()


def test_windows_localappdata_and_home_fallback(tmp_path: Path) -> None:
    home = tmp_path / "home"
    local = tmp_path / "local-app-data"

    assert resolve_data_dir(
        environ={"LOCALAPPDATA": str(local)},
        platform_name="win32",
        home=home,
    ) == (local / "AhThereItIs").resolve()

    assert resolve_data_dir(
        environ={"LOCALAPPDATA": "  "},
        platform_name="win32",
        home=home,
    ) == (home / "AppData" / "Local" / "AhThereItIs").resolve()

    assert resolve_data_dir(
        environ={}, platform_name="win32", home=home,
    ) == (home / "AppData" / "Local" / "AhThereItIs").resolve()
    assert default_database_path(
        environ={"LOCALAPPDATA": str(local)}, platform_name="win32", home=home,
    ) == (local / "AhThereItIs" / "inventory.db").resolve()


def test_data_dir_override_expands_home_and_ignores_blank(tmp_path: Path) -> None:
    home = tmp_path / "home"

    assert resolve_data_dir(
        environ={"AH_THERE_IT_IS_DATA_DIR": "~/inventory-data"},
        platform_name="linux",
        home=home,
    ) == (home / "inventory-data").resolve()

    assert resolve_data_dir(
        environ={
            "AH_THERE_IT_IS_DATA_DIR": " ",
            "XDG_DATA_HOME": str(tmp_path / "xdg"),
        },
        platform_name="linux",
        home=home,
    ) == (tmp_path / "xdg" / "ah-there-it-is").resolve()


def test_relative_data_base_is_anchored_to_home_not_cwd(tmp_path: Path) -> None:
    home = tmp_path / "home"

    assert resolve_data_dir(
        environ={"AH_THERE_IT_IS_DATA_DIR": "relative-data"},
        platform_name="linux",
        home=home,
    ) == (home / "relative-data").resolve()


def test_database_url_override_precedence_and_blank_handling(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    explicit = "  sqlite:////custom/location.db  "

    assert resolve_database_url(
        {
            "AH_THERE_IT_IS_DATA_DIR": str(data_dir),
            "AH_THERE_IT_IS_DATABASE_URL": explicit,
        }
    ) == explicit

    expected = f"sqlite:///{(data_dir / 'inventory.db').resolve().as_posix()}"
    assert resolve_database_url(
        {
            "AH_THERE_IT_IS_DATA_DIR": str(data_dir),
            "AH_THERE_IT_IS_DATABASE_URL": "   ",
        }
    ) == expected


def test_default_settings_and_get_settings_are_cwd_independent(
    tmp_path: Path,
    monkeypatch,
) -> None:
    data_dir = tmp_path / "stable-data"
    cwd_a = tmp_path / "cwd-a"
    cwd_b = tmp_path / "cwd-b"
    cwd_a.mkdir()
    cwd_b.mkdir()
    monkeypatch.setenv("AH_THERE_IT_IS_DATA_DIR", str(data_dir))
    monkeypatch.delenv("AH_THERE_IT_IS_DATABASE_URL", raising=False)

    monkeypatch.chdir(cwd_a)
    direct_a = Settings().database_url
    get_settings.cache_clear()
    cached_a = get_settings().database_url

    monkeypatch.chdir(cwd_b)
    direct_b = Settings().database_url
    get_settings.cache_clear()
    cached_b = get_settings().database_url

    expected = f"sqlite:///{(data_dir / 'inventory.db').resolve().as_posix()}"
    assert direct_a == direct_b == cached_a == cached_b == expected
    assert not data_dir.exists()


def test_path_resolution_and_settings_create_no_directories(
    tmp_path: Path,
    monkeypatch,
) -> None:
    data_dir = tmp_path / "missing" / "nested"
    monkeypatch.setenv("AH_THERE_IT_IS_DATA_DIR", str(data_dir))
    monkeypatch.delenv("AH_THERE_IT_IS_DATABASE_URL", raising=False)

    assert resolve_data_dir() == data_dir.resolve()
    assert default_database_path() == data_dir.resolve() / "inventory.db"
    assert default_database_url().startswith("sqlite:///")
    assert Settings().database_url.endswith("/inventory.db")
    get_settings.cache_clear()
    assert get_settings().database_url.endswith("/inventory.db")
    assert not data_dir.exists()


def test_explicit_upgrade_creates_stable_default_parent(
    tmp_path: Path,
    monkeypatch,
) -> None:
    data_dir = tmp_path / "missing" / "stable-data"
    database = data_dir / "inventory.db"
    monkeypatch.setenv("AH_THERE_IT_IS_DATA_DIR", str(data_dir))
    monkeypatch.delenv("AH_THERE_IT_IS_DATABASE_URL", raising=False)
    monkeypatch.setattr(sys, "argv", ["storage_cli", "upgrade"])
    get_settings.cache_clear()
    try:
        storage_cli_main()
    finally:
        get_settings.cache_clear()

    assert database.is_file()
    assert validate_database(database).alembic_revision == CURRENT_SCHEMA_REVISION


def test_explicit_upgrade_preserves_absolute_database_override(
    tmp_path: Path,
    monkeypatch,
) -> None:
    data_dir = tmp_path / "unused-data"
    database = tmp_path / "custom" / "absolute.db"
    url = f"sqlite:///{database}"
    monkeypatch.setenv("AH_THERE_IT_IS_DATA_DIR", str(data_dir))
    monkeypatch.setenv("AH_THERE_IT_IS_DATABASE_URL", url)
    monkeypatch.setattr(sys, "argv", ["storage_cli", "upgrade"])
    get_settings.cache_clear()
    try:
        storage_cli_main()
    finally:
        get_settings.cache_clear()

    assert database.is_file()
    assert not data_dir.exists()
    assert validate_database(database).alembic_revision == CURRENT_SCHEMA_REVISION



def test_create_app_with_default_settings_does_not_create_data_dir(
    tmp_path: Path,
    monkeypatch,
) -> None:
    data_dir = tmp_path / "missing-app-data"
    monkeypatch.setenv("AH_THERE_IT_IS_DATA_DIR", str(data_dir))
    monkeypatch.delenv("AH_THERE_IT_IS_DATABASE_URL", raising=False)
    get_settings.cache_clear()
    application = None
    try:
        application = create_app()
        assert not data_dir.exists()
    finally:
        get_settings.cache_clear()
        if application is not None and hasattr(application.state, "engine"):
            application.state.engine.dispose()
