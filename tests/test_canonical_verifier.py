from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from tools.agent import canonical_verifier as verifier


FAKE_MAKE = f'''#!{sys.executable}
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

assert len(sys.argv) == 2, sys.argv
recipe = sys.argv[1]
with open(os.environ["FAKE_MAKE_CALLS"], "a", encoding="utf-8") as calls:
    calls.write(recipe + "\\n")
print("stdout-" + recipe, flush=True)
print("stderr-" + recipe, file=sys.stderr, flush=True)
if os.environ.get("FAKE_MAKE_DELAY_RECIPE") == recipe:
    time.sleep(float(os.environ.get("FAKE_MAKE_DELAY_SECONDS", "0.4")))
if os.environ.get("FAKE_MAKE_FAIL_RECIPE") == recipe:
    raise SystemExit(7)
if os.environ.get("FAKE_MAKE_LARGE_RECIPE") == recipe:
    payload = b"x" * 1600000
    sys.stdout.buffer.write(payload)
    sys.stdout.buffer.flush()
    sys.stderr.buffer.write(b"y" * 1600000)
    sys.stderr.buffer.flush()
if os.environ.get("FAKE_MAKE_HANG_RECIPE") == recipe:
    child_code = "import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(60)"
    child = subprocess.Popen([sys.executable, "-c", child_code])
    Path(os.environ["FAKE_MAKE_CHILD_PID_FILE"]).write_text(str(child.pid), encoding="ascii")
    while True:
        time.sleep(0.05)
'''


@pytest.fixture
def verifier_workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "-C", str(repo), "init", "--initial-branch=main"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "Verifier Test"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "verifier@example.invalid"], check=True)
    (repo / "README.md").write_text("test repo\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "README.md"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-m", "initial"], check=True, capture_output=True)

    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    fake_make = fake_bin / "make"
    fake_make.write_text(FAKE_MAKE, encoding="utf-8")
    fake_make.chmod(0o755)
    calls = tmp_path / "make-calls.log"
    child_pid = tmp_path / "child.pid"
    monkeypatch.setenv("PATH", str(fake_bin) + os.pathsep + os.environ.get("PATH", ""))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("FAKE_MAKE_CALLS", str(calls))
    monkeypatch.setenv("FAKE_MAKE_CHILD_PID_FILE", str(child_pid))
    return {
        "root": tmp_path,
        "repo": repo,
        "fake_make": fake_make,
        "calls": calls,
        "child_pid": child_pid,
        "runs": tmp_path / "state" / "runs",
    }


def _state(workspace: dict[str, Path], name: str = "run-a") -> Path:
    return workspace["runs"] / name


def _start(
    workspace: dict[str, Path],
    name: str = "run-a",
    *,
    timeout_seconds: float | None = None,
) -> dict:
    return verifier.start_run(
        repo_path=str(workspace["repo"]),
        state_dir=str(_state(workspace, name)),
        timeout_seconds=timeout_seconds,
    )


def _wait_for_terminal(state_dir: Path, timeout: float = 15.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status = verifier.status_run(state_dir=str(state_dir))
        if status.get("status") in verifier._TERMINAL_STATUSES:
            return status
        if status.get("status") in {"invalid", "orphaned_command"}:
            raise AssertionError(f"verification run entered an unsafe state: {status}")
        time.sleep(0.02)
    raise AssertionError(f"verification run did not reach a terminal state: {state_dir}")


def _calls(workspace: dict[str, Path]) -> list[str]:
    if not workspace["calls"].exists():
        return []
    return workspace["calls"].read_text(encoding="utf-8").splitlines()


def _partial_state(
    workspace: dict[str, Path],
    name: str = "resume-run",
    *,
    failed_first_check: bool = False,
) -> Path:
    repo = workspace["repo"]
    run_dir = _state(workspace, name)
    run_dir.mkdir(parents=True, mode=0o700)
    state = verifier._initial_state(
        repo=repo,
        state_dir=run_dir,
        head_sha=verifier._git_head(repo),
        make_path=str(workspace["fake_make"]),
        timeout_seconds=60.0,
    )
    stdout = run_dir / "01-check-attempt-1.stdout.log"
    stderr = run_dir / "01-check-attempt-1.stderr.log"
    stdout.write_text("first check output\n", encoding="utf-8")
    stderr.write_text("first check error stream\n", encoding="utf-8")
    state["attempts"][0] = 1
    state["next_index"] = 1
    state["checks"] = [
        {
            "index": 0,
            "recipe": "check",
            "command": ["make", "check"],
            "attempt": 1,
            "head_sha": state["head_sha"],
            "started_at": "2026-09-24T00:00:00Z",
            "finished_at": "2026-09-24T00:00:01Z",
            "duration_seconds": 1.0,
            "exit_code": 7 if failed_first_check else 0,
            "status": "failed" if failed_first_check else "success",
            "timed_out": False,
            "stdout": {"path": stdout.name, "bytes_seen": 20, "bytes_saved": 20, "truncated": False},
            "stderr": {"path": stderr.name, "bytes_seen": 24, "bytes_saved": 24, "truncated": False},
        }
    ]
    state["status"] = "interrupted"
    state["pid"] = 2**30
    state["pgid"] = 2**30
    state["process_start_ticks"] = 1
    verifier._write_state(run_dir, state)
    return run_dir


def test_runs_exact_canonical_order_with_durable_head_and_stream_logs(
    verifier_workspace: dict[str, Path],
) -> None:
    started = _start(verifier_workspace)
    assert started["status"] == "running"
    result = _wait_for_terminal(_state(verifier_workspace))

    assert result["status"] == "passed"
    summary = result["summary"]
    assert [check["recipe"] for check in summary["checks"]] == list(verifier.CANONICAL_RECIPES)
    assert _calls(verifier_workspace) == list(verifier.CANONICAL_RECIPES)
    assert summary["recipes"] == list(verifier.CANONICAL_RECIPES)
    assert summary["head_sha"] == subprocess.run(
        ["git", "-C", str(verifier_workspace["repo"]), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    for check in summary["checks"]:
        assert check["command"] == ["make", check["recipe"]]
        assert check["head_sha"] == summary["head_sha"]
        assert check["exit_code"] == 0
        assert check["status"] == "success"
        assert check["started_at"] and check["finished_at"]
        assert check["duration_seconds"] >= 0
        assert (Path(started["state_dir"]) / check["stdout"]["path"]).read_text().startswith(
            "stdout-" + check["recipe"]
        )
        assert (Path(started["state_dir"]) / check["stderr"]["path"]).read_text().startswith(
            "stderr-" + check["recipe"]
        )
    assert not list(Path(started["state_dir"]).glob("*.tmp"))


def test_failure_stops_at_first_failed_recipe(verifier_workspace: dict[str, Path], monkeypatch) -> None:
    monkeypatch.setenv("FAKE_MAKE_FAIL_RECIPE", "corpus-check")

    started = _start(verifier_workspace)
    result = _wait_for_terminal(_state(verifier_workspace))

    assert started["status"] == "running"
    assert result["status"] == "failed"
    assert [check["recipe"] for check in result["summary"]["checks"]] == [
        "check",
        "migration-check",
        "corpus-check",
    ]
    assert result["summary"]["checks"][-1]["exit_code"] == 7
    assert _calls(verifier_workspace) == ["check", "migration-check", "corpus-check"]


def test_logs_are_bounded_and_include_both_stream_ends(verifier_workspace: dict[str, Path], monkeypatch) -> None:
    monkeypatch.setenv("FAKE_MAKE_LARGE_RECIPE", "check")

    _start(verifier_workspace)
    result = _wait_for_terminal(_state(verifier_workspace))

    assert result["status"] == "passed"
    check = result["summary"]["checks"][0]
    for stream, expected in (("stdout", b"x"), ("stderr", b"y")):
        metadata = check[stream]
        payload = (_state(verifier_workspace) / metadata["path"]).read_bytes()
        assert metadata["bytes_seen"] == 1_600_000 + len((f"{stream}-check\n").encode())
        assert metadata["truncated"] is True
        assert metadata["bytes_saved"] <= verifier.MAX_LOG_BYTES
        assert len(payload) == metadata["bytes_saved"]
        assert payload.startswith((f"{stream}-check\n").encode())
        assert verifier._LOG_TRUNCATION_MARKER in payload
        assert payload.endswith(expected * 100)


def test_timeout_kills_the_whole_make_process_group(
    verifier_workspace: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAKE_MAKE_HANG_RECIPE", "check")

    _start(verifier_workspace, timeout_seconds=1.0)
    result = _wait_for_terminal(_state(verifier_workspace), timeout=10)

    assert result["status"] == "timed_out"
    assert result["summary"]["checks"][0]["timed_out"] is True
    assert result["summary"]["checks"][0]["status"] == "timed_out"
    assert verifier_workspace["child_pid"].exists()
    child_pid = int(verifier_workspace["child_pid"].read_text(encoding="ascii"))
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        info = verifier._read_proc_stat(child_pid)
        if info is None or info["state"] in {"Z", "X"}:
            break
        time.sleep(0.02)
    info = verifier._read_proc_stat(child_pid)
    assert info is None or info["state"] in {"Z", "X"}
    assert _calls(verifier_workspace) == ["check"]


def test_status_and_resume_do_not_launch_duplicate_when_supervisor_is_alive(
    verifier_workspace: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAKE_MAKE_DELAY_RECIPE", "check")
    monkeypatch.setenv("FAKE_MAKE_DELAY_SECONDS", "0.7")

    started = _start(verifier_workspace)
    status = verifier.status_run(state_dir=str(_state(verifier_workspace)))
    resumed = verifier.resume_run(
        repo_path=str(verifier_workspace["repo"]),
        state_dir=str(_state(verifier_workspace)),
    )

    assert status["status"] == "running"
    assert status["pid"] == started["pid"]
    assert resumed["status"] == "already_running"
    assert _wait_for_terminal(_state(verifier_workspace))["status"] == "passed"
    assert _calls(verifier_workspace).count("check") == 1


def test_concurrent_verifier_for_same_repository_is_refused(
    verifier_workspace: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAKE_MAKE_HANG_RECIPE", "check")

    first = _start(verifier_workspace, "concurrent-one", timeout_seconds=0.3)
    second = _start(verifier_workspace, "concurrent-two", timeout_seconds=0.3)

    assert first["status"] == "running"
    assert second["status"] == "already_running"
    assert not _state(verifier_workspace, "concurrent-two").exists()
    assert _wait_for_terminal(_state(verifier_workspace, "concurrent-one"))["status"] == "timed_out"


def test_resume_continues_only_remaining_same_head_recipes(verifier_workspace: dict[str, Path]) -> None:
    run_dir = _partial_state(verifier_workspace)

    before = verifier.status_run(state_dir=str(run_dir))
    resumed = verifier.resume_run(
        repo_path=str(verifier_workspace["repo"]),
        state_dir=str(run_dir),
    )
    after = _wait_for_terminal(run_dir)

    assert before["status"] == "interrupted"
    assert before["resume_allowed"] is True
    assert resumed["status"] == "running"
    assert after["status"] == "passed"
    assert [check["recipe"] for check in after["summary"]["checks"]] == list(
        verifier.CANONICAL_RECIPES
    )
    assert _calls(verifier_workspace) == list(verifier.CANONICAL_RECIPES[1:])
    assert after["state"]["resume_count"] == 1


def test_resume_rejects_head_change_and_does_not_execute_recipes(verifier_workspace: dict[str, Path]) -> None:
    run_dir = _partial_state(verifier_workspace, "head-changed")
    (verifier_workspace["repo"] / "later.txt").write_text("changed head\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(verifier_workspace["repo"]), "add", "later.txt"], check=True)
    subprocess.run(
        ["git", "-C", str(verifier_workspace["repo"]), "commit", "-m", "new head"],
        check=True,
        capture_output=True,
    )

    result = verifier.resume_run(
        repo_path=str(verifier_workspace["repo"]),
        state_dir=str(run_dir),
    )

    assert result["status"] == "resume_blocked"
    assert any("Git HEAD changed" in reason for reason in result["reasons"])
    assert _calls(verifier_workspace) == []


def test_resume_rejects_changed_command_definitions(verifier_workspace: dict[str, Path]) -> None:
    run_dir = _partial_state(verifier_workspace, "definitions-changed")
    state = verifier._read_state(run_dir)
    state["recipe_definitions_sha256"] = "a" * 64
    verifier._write_state(run_dir, state)

    result = verifier.resume_run(
        repo_path=str(verifier_workspace["repo"]),
        state_dir=str(run_dir),
    )

    assert result["status"] == "resume_blocked"
    assert any("definition digest differs" in reason for reason in result["reasons"])
    assert _calls(verifier_workspace) == []


def test_resume_rejects_any_previous_failed_check(verifier_workspace: dict[str, Path]) -> None:
    run_dir = _partial_state(verifier_workspace, "failed-before-resume", failed_first_check=True)

    result = verifier.resume_run(
        repo_path=str(verifier_workspace["repo"]),
        state_dir=str(run_dir),
    )

    assert result["status"] == "resume_blocked"
    assert any("did not succeed" in reason for reason in result["reasons"])
    assert _calls(verifier_workspace) == []


def test_run_state_must_live_outside_worktree(verifier_workspace: dict[str, Path]) -> None:
    with pytest.raises(verifier.VerifierError, match="outside"):
        verifier.start_run(
            repo_path=str(verifier_workspace["repo"]),
            state_dir=str(verifier_workspace["repo"] / "state-run"),
        )
    assert not (verifier_workspace["repo"] / "state-run").exists()


def test_status_blocks_resume_while_orphaned_make_group_is_alive(
    verifier_workspace: dict[str, Path],
) -> None:
    run_dir = _state(verifier_workspace, "orphaned-command")
    run_dir.mkdir(parents=True, mode=0o700)
    process = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    try:
        process_info = verifier._read_proc_stat(process.pid)
        assert process_info is not None
        state = verifier._initial_state(
            repo=verifier_workspace["repo"],
            state_dir=run_dir,
            head_sha=verifier._git_head(verifier_workspace["repo"]),
            make_path=str(verifier_workspace["fake_make"]),
            timeout_seconds=60.0,
        )
        state["attempts"][0] = 1
        state["active_command"] = {
            "index": 0,
            "recipe": "check",
            "attempt": 1,
            "started_at": "2026-09-24T00:00:00Z",
            "pid": process.pid,
            "pgid": process_info["pgrp"],
            "process_start_ticks": process_info["start_ticks"],
        }
        state["status"] = "interrupted"
        state["pid"] = 2**30
        state["pgid"] = 2**30
        state["process_start_ticks"] = 1
        verifier._write_state(run_dir, state)

        status = verifier.status_run(state_dir=str(run_dir))
        resume = verifier.resume_run(
            repo_path=str(verifier_workspace["repo"]),
            state_dir=str(run_dir),
        )

        assert status["status"] == "orphaned_command"
        assert status["current_recipe"] == "check"
        assert resume["status"] == "already_running"
        assert _calls(verifier_workspace) == []
    finally:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait(timeout=2)


def test_new_start_refuses_previous_orphaned_command_group(
    verifier_workspace: dict[str, Path],
) -> None:
    previous_dir = _state(verifier_workspace, "previous-orphan")
    previous_dir.mkdir(parents=True, mode=0o700)
    process = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    lock_fd: int | None = None
    try:
        process_info = verifier._read_proc_stat(process.pid)
        assert process_info is not None
        state = verifier._initial_state(
            repo=verifier_workspace["repo"],
            state_dir=previous_dir,
            head_sha=verifier._git_head(verifier_workspace["repo"]),
            make_path=str(verifier_workspace["fake_make"]),
            timeout_seconds=60.0,
        )
        state["attempts"][0] = 1
        state["active_command"] = {
            "index": 0,
            "recipe": "check",
            "attempt": 1,
            "started_at": "2026-09-24T00:00:00Z",
            "pid": process.pid,
            "pgid": process_info["pgrp"],
            "process_start_ticks": process_info["start_ticks"],
        }
        state["status"] = "interrupted"
        state["pid"] = 2**30
        state["pgid"] = 2**30
        state["process_start_ticks"] = 1
        verifier._write_state(previous_dir, state)
        lock_path = verifier._lock_path(verifier_workspace["repo"])
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock_fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
        verifier._write_lock_owner(
            lock_fd,
            {"run_id": previous_dir.name, "state_dir": str(previous_dir)},
        )
        os.close(lock_fd)
        lock_fd = None

        result = _start(verifier_workspace, "new-run")

        assert result["status"] == "already_running"
        assert result["active_run"]["status"] == "orphaned_command"
        assert not _state(verifier_workspace, "new-run").exists()
        assert _calls(verifier_workspace) == []
    finally:
        if lock_fd is not None:
            os.close(lock_fd)
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait(timeout=2)
