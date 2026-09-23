"""Side-effect-free per-user application data paths."""

from __future__ import annotations

from collections.abc import Mapping
import os
from pathlib import Path
import sys


def resolve_data_dir(
    *,
    environ: Mapping[str, str] | None = None,
    platform_name: str | None = None,
    home: str | Path | None = None,
) -> Path:
    """Resolve the per-user data directory without creating it."""
    env = os.environ if environ is None else environ
    platform = sys.platform if platform_name is None else platform_name
    home_path = _home_path(home)

    override = _nonblank(env.get("AH_THERE_IT_IS_DATA_DIR"))
    if override is not None:
        return _absolute_user_path(override, home_path)

    if platform == "darwin":
        return (
            home_path / "Library" / "Application Support" / "AhThereItIs"
        ).resolve()

    if platform.startswith("win"):
        local_app_data = _nonblank(env.get("LOCALAPPDATA"))
        if local_app_data is not None:
            base = _absolute_user_path(local_app_data, home_path)
        else:
            base = home_path / "AppData" / "Local"
        return (base / "AhThereItIs").resolve()

    xdg_data_home = _nonblank(env.get("XDG_DATA_HOME"))
    if xdg_data_home is not None:
        base = _absolute_user_path(xdg_data_home, home_path)
    else:
        base = home_path / ".local" / "share"
    return (base / "ah-there-it-is").resolve()


def default_database_path(
    *,
    environ: Mapping[str, str] | None = None,
    platform_name: str | None = None,
    home: str | Path | None = None,
) -> Path:
    return resolve_data_dir(
        environ=environ,
        platform_name=platform_name,
        home=home,
    ) / "inventory.db"


def default_database_url(
    *,
    environ: Mapping[str, str] | None = None,
    platform_name: str | None = None,
    home: str | Path | None = None,
) -> str:
    path = default_database_path(
        environ=environ,
        platform_name=platform_name,
        home=home,
    )
    return f"sqlite:///{path.as_posix()}"


def _home_path(home: str | Path | None) -> Path:
    if home is None:
        return Path.home().expanduser().resolve()
    return Path(home).expanduser().resolve()


def _absolute_user_path(value: str, home: Path) -> Path:
    if value == "~":
        return home
    if value.startswith("~/") or value.startswith("~\\"):
        candidate = home / value[2:]
    else:
        candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        candidate = home / candidate
    return candidate.resolve()


def _nonblank(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    return value
