"""Release and secret boundaries of the installed user services."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_telegram_secret_is_only_loaded_by_telegram_unit() -> None:
    web = (ROOT / "deploy/systemd/ah-there-it-is-web.service").read_text()
    telegram = (ROOT / "deploy/systemd/ah-there-it-is-telegram.service").read_text()
    common = "EnvironmentFile=%h/.local/state/ah-there-it-is/runtime.env"
    secret = "EnvironmentFile=%h/.local/state/ah-there-it-is/telegram.env"
    assert common in web and common in telegram
    assert secret not in web and secret in telegram
    assert "UnsetEnvironment=AH_THERE_IT_IS_TELEGRAM_BOT_TOKEN" in web


def test_shipped_web_unit_requests_trusted_lan_bind_with_explicit_ack() -> None:
    web = (ROOT / "deploy/systemd/ah-there-it-is-web.service").read_text()
    assert "serve --host 0.0.0.0 --port 8000 --allow-nonlocal" in web
    assert "schema-check --require-production" in web


def test_installer_accepts_reviewed_web_command_and_rejects_loopback(tmp_path, monkeypatch) -> None:
    import pytest

    from deploy import install_user_units

    unit_dir = tmp_path / "units"
    unit_dir.mkdir()
    for name in install_user_units.UNIT_NAMES:
        (unit_dir / name).write_text("stable copied unit")

    web_state = {
        "FragmentPath": str(unit_dir / install_user_units.UNIT_NAMES[0]),
        "NeedDaemonReload": "no",
        "ExecStartPre": "ah-there-it-is schema-check --require-production",
        "ExecStart": (
            "/current/.venv/bin/ah-there-it-is serve --host 0.0.0.0 "
            "--port 8000 --allow-nonlocal"
        ),
        "EnvironmentFiles": "runtime.env",
        "UnsetEnvironment": (
            "AH_THERE_IT_IS_TELEGRAM_BOT_TOKEN "
            "AH_THERE_IT_IS_TELEGRAM_ALLOWED_USER_ID"
        ),
    }
    telegram_state = {
        "FragmentPath": str(unit_dir / install_user_units.UNIT_NAMES[1]),
        "NeedDaemonReload": "no",
        "ExecStartPre": "ah-there-it-is schema-check --require-production",
        "ExecStart": "/current/.venv/bin/ah-there-it-is",
        "EnvironmentFiles": "runtime.env telegram.env",
    }
    states = iter((web_state, telegram_state))
    monkeypatch.setattr(install_user_units, "_properties", lambda _name: next(states))
    monkeypatch.setattr("builtins.print", lambda *_args, **_kwargs: None)

    install_user_units.verify_effective_units(unit_dir)

    states = iter((
        {**web_state, "ExecStart": web_state["ExecStart"].replace("0.0.0.0", "127.0.0.1")},
        telegram_state,
    ))
    monkeypatch.setattr(install_user_units, "_properties", lambda _name: next(states))
    with pytest.raises(RuntimeError, match="trusted-LAN command"):
        install_user_units.verify_effective_units(unit_dir)


def test_release_switch_retains_stable_unit_files_after_old_checkout_deleted(
    tmp_path: Path,
) -> None:
    from deploy.install_user_units import copy_units, switch_release

    old = tmp_path / "old"
    new = tmp_path / "new"
    units = tmp_path / "user-units"
    app = tmp_path / "app"
    app.mkdir()
    for release in (old, new):
        (release / "deploy/systemd").mkdir(parents=True)
        (release / ".venv/bin").mkdir(parents=True)
        (release / ".venv/bin/ah-there-it-is").touch()
        for source in (ROOT / "deploy/systemd").glob("*.service"):
            (release / "deploy/systemd" / source.name).write_bytes(source.read_bytes())
    current = app / "current"
    current.symlink_to(old, target_is_directory=True)

    units.mkdir()
    (units / "ah-there-it-is-web.service").symlink_to(
        old / "deploy/systemd/ah-there-it-is-web.service",
    )
    copy_units(old / "deploy/systemd", units)
    assert not (units / "ah-there-it-is-web.service").is_symlink()
    switch_release(current, new)
    new_web = new / "deploy/systemd/ah-there-it-is-web.service"
    new_web.write_text(new_web.read_text() + "\n# updated unit\n")
    copy_units(new / "deploy/systemd", units)
    for source in (ROOT / "deploy/systemd").glob("*.service"):
        assert (units / source.name).is_file()
        assert not (units / source.name).is_symlink()
        assert (units / source.name).read_bytes() == (
            new / "deploy/systemd" / source.name
        ).read_bytes()
    for path in (old / "deploy/systemd").glob("*.service"):
        path.unlink()
    assert current.resolve() == new.resolve()
    assert all((units / source.name).is_file()
               for source in (ROOT / "deploy/systemd").glob("*.service"))
