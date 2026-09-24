from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from tools.agent import codex_session


SCRIPT = Path(codex_session.__file__).resolve()

FAKE_CODEX = r"""#!/usr/bin/env python3
import hashlib
import json
import os
import signal
import subprocess
import sys
import time

if sys.argv[1:] == ["--version"]:
    print("fake-codex 1.2.3")
    raise SystemExit(0)

assert sys.argv[1:] == ["exec", "--json", "--full-auto", "-"]
prompt = sys.stdin.buffer.read()
mode = os.environ.get("CODEX_SESSION_TEST_MODE", "normal")
payload = {
    "argv": sys.argv[1:],
    "prompt_sha256": hashlib.sha256(prompt).hexdigest(),
    "mode": mode,
}
if mode == "spawn_ignore":
    child_code = "import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(60)"
    child = subprocess.Popen([sys.executable, "-c", child_code])
    payload["child_pid"] = child.pid
if mode == "graceful":
    def _stop(_signum, _frame):
        raise SystemExit(0)
    signal.signal(signal.SIGTERM, _stop)
if mode in {"ignore", "spawn_ignore"}:
    signal.signal(signal.SIGTERM, signal.SIG_IGN)

print(json.dumps(payload), flush=True)
print("fake stderr line", file=sys.stderr, flush=True)

if mode in {"hold", "graceful", "ignore", "spawn_ignore"}:
    while True:
        time.sleep(0.05)
if mode == "fail":
    raise SystemExit(7)
"""


@pytest.fixture
def session_workspace(tmp_path: Path) -> dict[str, Path]:
    repo = tmp_path / "repo"
    repo.mkdir()
    prompt = tmp_path / "issued-prompt.bin"
    prompt.write_bytes(b"exact prompt bytes\x00with newline\n")
    state = tmp_path / "state"
    codex = tmp_path / "fake-codex"
    codex.write_text(FAKE_CODEX, encoding="utf-8")
    codex.chmod(0o755)
    return {"repo": repo, "prompt": prompt, "state": state, "codex": codex}


def _start(paths: dict[str, Path], run_id: str) -> dict:
    return codex_session.start_run(
        run_id=run_id,
        repo_path=str(paths["repo"]),
        prompt_file=str(paths["prompt"]),
        state_dir=str(paths["state"]),
        codex_bin=str(paths["codex"]),
    )


def _wait_for_terminal(state: Path, run_id: str, timeout: float = 5.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status = codex_session.status_run(run_id=run_id, state_dir=str(state))
        if status.get("status") in {"completed", "failed", "terminated", "invalid", "stale"}:
            return status
        time.sleep(0.02)
    raise AssertionError(f"run {run_id} did not reach a terminal state")


def _wait_for_stdout(state: Path, run_id: str, marker: str, timeout: float = 5.0) -> str:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        tail = codex_session.tail_run(
            run_id=run_id,
            state_dir=str(state),
            stream="stdout",
        )
        if marker in tail["content"]:
            return tail["content"]
        status = codex_session.status_run(run_id=run_id, state_dir=str(state))
        if status.get("status") in {"completed", "failed", "terminated", "invalid", "stale"}:
            raise AssertionError(f"run ended before writing expected output: {status}")
        time.sleep(0.02)
    raise AssertionError(f"run {run_id} did not write expected output")


def _cleanup(paths: dict[str, Path], run_id: str) -> None:
    status = codex_session.status_run(run_id=run_id, state_dir=str(paths["state"]))
    if status.get("status") == "running":
        codex_session.terminate_run(
            run_id=run_id,
            state_dir=str(paths["state"]),
            grace_seconds=0.1,
        )


def _is_live(pid: int) -> bool:
    info = codex_session._read_proc_stat(pid)
    return info is not None and info["state"] not in {"Z", "X"}


def test_prompt_is_passed_exactly_and_logs_are_separate_without_secret_dump(
    session_workspace: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CODEX_SESSION_TEST_MODE", "normal")
    secret = "test-secret-that-must-not-be-persisted"
    monkeypatch.setenv("CODEX_SESSION_TEST_SECRET", secret)
    run_id = "prompt-capture"

    started = _start(session_workspace, run_id)
    try:
        assert started["status"] == "running"
        assert started["prompt_sha256"] == hashlib.sha256(
            session_workspace["prompt"].read_bytes()
        ).hexdigest()
        result = _wait_for_terminal(session_workspace["state"], run_id)
        assert result["status"] == "completed"
        assert result["exit_code"] == 0

        output = codex_session.tail_run(
            run_id=run_id,
            state_dir=str(session_workspace["state"]),
            stream="stdout",
        )["content"]
        record = json.loads(output.splitlines()[0])
        assert record["argv"] == ["exec", "--json", "--full-auto", "-"]
        assert record["prompt_sha256"] == started["prompt_sha256"]
        assert "fake stderr line" not in output

        error = codex_session.tail_run(
            run_id=run_id,
            state_dir=str(session_workspace["state"]),
            stream="stderr",
        )["content"]
        assert error.strip() == "fake stderr line"

        run_dir = Path(started["run_dir"])
        metadata = json.loads((run_dir / "metadata.json").read_text(encoding="utf-8"))
        assert metadata["codex_version"] == "fake-codex 1.2.3"
        assert metadata["repo_path"] == str(session_workspace["repo"])
        assert "environment" not in metadata
        for path in run_dir.iterdir():
            if path.is_file():
                assert secret not in path.read_text(encoding="utf-8", errors="replace")
        assert not (session_workspace["repo"] / run_id).exists()
        assert set(path.name for path in run_dir.iterdir()) >= {
            "metadata.json",
            "stdout.jsonl",
            "stderr.log",
            "result.json",
        }
    finally:
        _cleanup(session_workspace, run_id)


def test_nonzero_codex_exit_is_recorded(session_workspace: dict[str, Path], monkeypatch) -> None:
    monkeypatch.setenv("CODEX_SESSION_TEST_MODE", "fail")
    run_id = "nonzero"
    _start(session_workspace, run_id)
    try:
        result = _wait_for_terminal(session_workspace["state"], run_id)
        assert result["status"] == "completed"
        assert result["exit_code"] == 7
    finally:
        _cleanup(session_workspace, run_id)


def test_start_cli_detaches_and_worker_survives_initiating_process(
    session_workspace: dict[str, Path],
) -> None:
    run_id = "detached"
    env = os.environ.copy()
    env["CODEX_SESSION_TEST_MODE"] = "hold"
    started_at = time.monotonic()
    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "start",
            "--run-id",
            run_id,
            "--repo",
            str(session_workspace["repo"]),
            "--prompt-file",
            str(session_workspace["prompt"]),
            "--state-dir",
            str(session_workspace["state"]),
            "--codex-bin",
            str(session_workspace["codex"]),
        ],
        cwd=session_workspace["repo"],
        env=env,
        capture_output=True,
        text=True,
        timeout=3,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert time.monotonic() - started_at < 2.0
    started = json.loads(completed.stdout)
    try:
        state = codex_session.status_run(run_id=run_id, state_dir=str(session_workspace["state"]))
        assert state["status"] == "running"
        assert state["supervisor_alive"] is True
        _wait_for_stdout(session_workspace["state"], run_id, "prompt_sha256")
    finally:
        _cleanup(session_workspace, run_id)


def test_existing_run_id_is_never_reused(
    session_workspace: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CODEX_SESSION_TEST_MODE", "hold")
    run_id = "duplicate"
    started = _start(session_workspace, run_id)
    metadata_before = (Path(started["run_dir"]) / "metadata.json").read_bytes()
    stdout_before = (Path(started["run_dir"]) / "stdout.jsonl").read_bytes()
    try:
        with pytest.raises(codex_session.SessionError, match="never reused"):
            _start(session_workspace, run_id)
        assert (Path(started["run_dir"]) / "metadata.json").read_bytes() == metadata_before
        assert (Path(started["run_dir"]) / "stdout.jsonl").read_bytes() == stdout_before
        assert codex_session.status_run(
            run_id=run_id, state_dir=str(session_workspace["state"])
        )["status"] == "running"
    finally:
        _cleanup(session_workspace, run_id)


def test_tail_is_bounded_by_bytes_and_lines(
    session_workspace: dict[str, Path],
) -> None:
    run_id = "tail"
    run_dir = session_workspace["state"] / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "metadata.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "schema_version": 1,
                "repo_path": str(session_workspace["repo"]),
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "stdout.jsonl").write_bytes(b"line-one\nline-two\nline-three\n")
    tail = codex_session.tail_run(
        run_id=run_id,
        state_dir=str(session_workspace["state"]),
        stream="stdout",
        max_bytes=20,
        max_lines=2,
    )
    assert tail["bytes_read"] == 20
    assert len(tail["content"].splitlines()) <= 2
    assert tail["truncated"] is True


def test_status_reports_invalid_and_stale_durable_state(
    session_workspace: dict[str, Path],
) -> None:
    invalid_dir = session_workspace["state"] / "invalid"
    invalid_dir.mkdir(parents=True)
    (invalid_dir / "metadata.json").write_text("{", encoding="utf-8")
    invalid = codex_session.status_run(
        run_id="invalid",
        state_dir=str(session_workspace["state"]),
    )
    assert invalid["status"] == "invalid"

    stale_dir = session_workspace["state"] / "stale"
    stale_dir.mkdir()
    (stale_dir / "metadata.json").write_text(
        json.dumps(
            {
                "run_id": "stale",
                "schema_version": 1,
                "repo_path": str(session_workspace["repo"]),
                "pid": 2**30,
                "pgid": 2**30,
                "process_start_ticks": 1,
            }
        ),
        encoding="utf-8",
    )
    stale = codex_session.status_run(
        run_id="stale",
        state_dir=str(session_workspace["state"]),
    )
    assert stale["status"] == "stale"


def test_status_rejects_run_state_inside_worktree(
    session_workspace: dict[str, Path],
) -> None:
    run_id = "nested-state"
    nested_state = session_workspace["repo"] / "state"
    run_dir = nested_state / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "metadata.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "schema_version": 1,
                "repo_path": str(session_workspace["repo"]),
                "pid": 2**30,
                "pgid": 2**30,
                "process_start_ticks": 1,
            }
        ),
        encoding="utf-8",
    )
    status = codex_session.status_run(run_id=run_id, state_dir=str(nested_state))
    assert status["status"] == "invalid"
    assert "outside the repository" in status["error"]


def test_state_directory_must_be_outside_worktree(
    session_workspace: dict[str, Path],
) -> None:
    with pytest.raises(codex_session.SessionError, match="outside the repository"):
        codex_session.start_run(
            run_id="inside-worktree",
            repo_path=str(session_workspace["repo"]),
            prompt_file=str(session_workspace["prompt"]),
            state_dir=str(session_workspace["repo"] / "state"),
            codex_bin=str(session_workspace["codex"]),
        )
    assert not (session_workspace["repo"] / "state").exists()


def test_graceful_group_termination_records_outcome(
    session_workspace: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CODEX_SESSION_TEST_MODE", "graceful")
    run_id = "graceful-stop"
    _start(session_workspace, run_id)
    try:
        _wait_for_stdout(session_workspace["state"], run_id, "prompt_sha256")
        result = codex_session.terminate_run(
            run_id=run_id,
            state_dir=str(session_workspace["state"]),
            grace_seconds=1.0,
        )
        assert result["status"] == "terminated"
        assert result["termination_outcome"] == "sigterm"
        term_state = json.loads(
            (session_workspace["state"] / run_id / "termination.json").read_text(
                encoding="utf-8"
            )
        )
        assert term_state["outcome"] in {
            "sigterm_completed",
            "worker_recorded_terminal_result",
        }
    finally:
        _cleanup(session_workspace, run_id)


def test_sigkill_escalation_terminates_process_group_descendants(
    session_workspace: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CODEX_SESSION_TEST_MODE", "spawn_ignore")
    run_id = "escalate"
    _start(session_workspace, run_id)
    try:
        output = _wait_for_stdout(session_workspace["state"], run_id, "child_pid")
        child_pid = json.loads(output.splitlines()[0])["child_pid"]
        result = codex_session.terminate_run(
            run_id=run_id,
            state_dir=str(session_workspace["state"]),
            grace_seconds=0.1,
        )
        assert result["status"] == "terminated"
        assert result["termination_outcome"] == "sigkill"
        deadline = time.monotonic() + 2
        while _is_live(child_pid) and time.monotonic() < deadline:
            time.sleep(0.02)
        assert not _is_live(child_pid)
        term_state = json.loads(
            (session_workspace["state"] / run_id / "termination.json").read_text(
                encoding="utf-8"
            )
        )
        assert term_state["outcome"] == "sigkill_completed"
    finally:
        _cleanup(session_workspace, run_id)


def test_missing_codex_is_a_durable_runner_failure(
    session_workspace: dict[str, Path],
) -> None:
    run_id = "missing-command"
    started = codex_session.start_run(
        run_id=run_id,
        repo_path=str(session_workspace["repo"]),
        prompt_file=str(session_workspace["prompt"]),
        state_dir=str(session_workspace["state"]),
        codex_bin=str(session_workspace["repo"] / "does-not-exist"),
    )
    try:
        result = _wait_for_terminal(session_workspace["state"], run_id)
        assert result["status"] == "failed"
        assert result["error_type"] == "FileNotFoundError"
        metadata_path = Path(started["run_dir"]) / "metadata.json"
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            if metadata["lifecycle_status"] == "failed":
                break
            time.sleep(0.02)
        assert metadata["lifecycle_status"] == "failed"
    finally:
        _cleanup(session_workspace, run_id)
