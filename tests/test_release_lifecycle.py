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
