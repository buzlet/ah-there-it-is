#!/usr/bin/env python3
"""Launch and supervise detached Codex CLI sessions on U24/POSIX."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

_RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_TERMINAL_STATUSES = {"completed", "failed", "terminated"}
_VALID_STREAMS = {"stdout": "stdout.jsonl", "stderr": "stderr.log"}
_WORKER_GATE_TIMEOUT_SECONDS = 15.0
_MAX_TAIL_BYTES = 1024 * 1024
_MAX_TAIL_LINES = 10000

_termination_requested = False


class SessionError(Exception):
    """An expected session validation or lifecycle error."""


def _utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )


def _validate_run_id(run_id: str) -> str:
    if not _RUN_ID_RE.fullmatch(run_id) or run_id in {".", ".."}:
        raise SessionError("run_id must be 1-128 safe filename characters")
    return run_id


def _resolve_repo_and_state(repo_path: str, state_dir: str) -> tuple[Path, Path]:
    repo = Path(repo_path).expanduser().resolve()
    state = Path(state_dir).expanduser().resolve()
    if not repo.is_dir():
        raise SessionError("repository path must be an existing directory")
    try:
        state.relative_to(repo)
    except ValueError:
        pass
    else:
        raise SessionError("state directory must be outside the repository worktree")
    return repo, state


def _run_dir(state_dir: str | Path, run_id: str, *, must_exist: bool = True) -> Path:
    safe_id = _validate_run_id(run_id)
    state = Path(state_dir).expanduser().resolve()
    run_dir = state / safe_id
    if run_dir.is_symlink():
        raise SessionError("run directory must not be a symlink")
    if must_exist and not run_dir.is_dir():
        raise SessionError("run directory does not exist")
    try:
        run_dir.resolve().relative_to(state)
    except ValueError as exc:
        raise SessionError("run directory escaped the state directory") from exc
    return run_dir


def _fsync_directory(directory: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    fd = os.open(directory, flags)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def _create_json_once(path: Path, payload: dict[str, Any]) -> bool:
    """Atomically create a terminal file without replacing an earlier result."""
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            return False
        _fsync_directory(path.parent)
        return True
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def _create_empty_file(path: Path) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _read_json(path: Path) -> dict[str, Any]:
    if path.is_symlink():
        raise SessionError(f"{path.name} must not be a symlink")
    try:
        with path.open("r", encoding="utf-8") as stream:
            value = json.load(stream)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SessionError(f"cannot read valid {path.name}") from exc
    if not isinstance(value, dict):
        raise SessionError(f"{path.name} must contain a JSON object")
    return value


def _read_optional_result(run_dir: Path, run_id: str) -> dict[str, Any] | None:
    path = run_dir / "result.json"
    if not path.exists() and not path.is_symlink():
        return None
    result = _read_json(path)
    if result.get("run_id") != run_id or result.get("status") not in _TERMINAL_STATUSES:
        raise SessionError("result.json has an invalid run identity or status")
    if result.get("status") == "completed" and not isinstance(result.get("exit_code"), int):
        raise SessionError("completed result has no integer exit code")
    return result


def _write_terminal_result(
    run_dir: Path,
    run_id: str,
    status: str,
    *,
    exit_code: int | None = None,
    termination_outcome: str | None = None,
    error_type: str | None = None,
    error_message: str | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "run_id": run_id,
        "status": status,
        "exit_code": exit_code,
        "finished_at": _utc_now(),
    }
    if termination_outcome is not None:
        result["termination_outcome"] = termination_outcome
    if error_type is not None:
        result["error_type"] = error_type[:120]
    if error_message is not None:
        result["error"] = " ".join(error_message.split())[:300]
    _create_json_once(run_dir / "result.json", result)
    saved = _read_json(run_dir / "result.json")
    try:
        metadata = _read_json(run_dir / "metadata.json")
        metadata["lifecycle_status"] = saved["status"]
        metadata["finished_at"] = saved["finished_at"]
        _atomic_json(run_dir / "metadata.json", metadata)
    except SessionError:
        pass
    return saved


def _prompt_sha256(prompt_path: Path) -> tuple[Any, str]:
    try:
        prompt = prompt_path.open("rb")
    except OSError as exc:
        raise SessionError("prompt file cannot be opened") from exc
    digest = hashlib.sha256()
    try:
        while True:
            block = prompt.read(1024 * 1024)
            if not block:
                break
            digest.update(block)
        prompt.seek(0)
    except OSError as exc:
        prompt.close()
        raise SessionError("prompt file cannot be read") from exc
    return prompt, digest.hexdigest()


def _codex_version(codex_bin: str, repo: Path) -> str | None:
    try:
        result = subprocess.run(
            [codex_bin, "--version"],
            cwd=repo,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=3.0,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    output = result.stdout.decode("utf-8", errors="replace").strip()
    if not output:
        return None
    return " ".join(output.split())[:200]


def _read_proc_stat(pid: int) -> dict[str, Any] | None:
    try:
        with open(f"/proc/{pid}/stat", "r", encoding="ascii") as stream:
            line = stream.read()
    except (FileNotFoundError, PermissionError, ProcessLookupError, OSError):
        return None
    closing_paren = line.rfind(")")
    if closing_paren < 0:
        return None
    fields = line[closing_paren + 2 :].split()
    if len(fields) <= 19:
        return None
    try:
        return {
            "pid": pid,
            "state": fields[0],
            "pgrp": int(fields[2]),
            "session": int(fields[3]),
            "start_ticks": int(fields[19]),
        }
    except ValueError:
        return None


def _group_state(metadata: dict[str, Any]) -> tuple[str, bool]:
    """Return (state, supervisor_alive), checking Linux process identity."""
    try:
        pid = int(metadata["pid"])
        pgid = int(metadata["pgid"])
        expected_start = int(metadata["process_start_ticks"])
    except (KeyError, TypeError, ValueError):
        return "invalid", False
    if pid <= 0 or pgid != pid or expected_start <= 0:
        return "invalid", False

    proc_root = Path("/proc")
    if not proc_root.is_dir():
        return "unverifiable", False

    supervisor_alive = False
    live_group_members = 0
    try:
        entries = list(proc_root.iterdir())
    except OSError:
        return "unverifiable", False
    for entry in entries:
        if not entry.name.isdecimal():
            continue
        info = _read_proc_stat(int(entry.name))
        if info is None or info["pgrp"] != pgid:
            continue
        if info["pid"] == pid:
            if info["start_ticks"] != expected_start:
                return "identity_mismatch", False
            if info["state"] not in {"Z", "X"}:
                supervisor_alive = True
        if info["state"] not in {"Z", "X"}:
            live_group_members += 1
    return ("live" if live_group_members else "dead", supervisor_alive)


def _metadata_for(run_dir: Path, run_id: str) -> dict[str, Any]:
    metadata = _read_json(run_dir / "metadata.json")
    if metadata.get("run_id") != run_id or metadata.get("schema_version") != 1:
        raise SessionError("metadata.json has an invalid run identity or schema")
    repo_path = metadata.get("repo_path")
    if not isinstance(repo_path, str) or not repo_path:
        raise SessionError("metadata.json has no repository path")
    repo = Path(repo_path).expanduser().resolve()
    try:
        run_dir.parent.resolve().relative_to(repo)
    except ValueError:
        pass
    else:
        raise SessionError("state directory must be outside the repository worktree")
    return metadata


def start_run(
    *,
    run_id: str,
    repo_path: str,
    prompt_file: str,
    state_dir: str,
    codex_bin: str = "codex",
    _hold_fd: int | None = None,
) -> dict[str, Any]:
    if os.name != "posix":
        raise SessionError("Codex session runner supports POSIX hosts only")
    if _hold_fd is not None and _hold_fd < 0:
        raise SessionError("inherited lock file descriptor must be non-negative")
    safe_id = _validate_run_id(run_id)
    repo, state = _resolve_repo_and_state(repo_path, state_dir)
    if not codex_bin or "\x00" in codex_bin:
        raise SessionError("Codex executable must be a non-empty command name or path")
    prompt_path = Path(prompt_file).expanduser().resolve()
    prompt, prompt_hash = _prompt_sha256(prompt_path)
    state.mkdir(parents=True, exist_ok=True, mode=0o700)
    run_dir = _run_dir(state, safe_id, must_exist=False)
    try:
        run_dir.mkdir(mode=0o700)
    except FileExistsError as exc:
        prompt.close()
        raise SessionError("run_id already exists; run IDs are never reused") from exc
    _fsync_directory(state)

    for filename in ("stdout.jsonl", "stderr.log"):
        _create_empty_file(run_dir / filename)

    metadata: dict[str, Any] = {
        "schema_version": 1,
        "run_id": safe_id,
        "pid": None,
        "pgid": None,
        "process_start_ticks": None,
        "repo_path": str(repo),
        "codex_command": Path(codex_bin).name or codex_bin,
        "codex_version": _codex_version(codex_bin, repo),
        "prompt_sha256": prompt_hash,
        "started_at": _utc_now(),
        "lifecycle_status": "starting",
    }
    _atomic_json(run_dir / "metadata.json", metadata)

    worker_argv = [
        sys.executable,
        str(Path(__file__).resolve()),
        "_worker",
        "--run-dir",
        str(run_dir),
        "--repo-path",
        str(repo),
        "--codex-bin",
        codex_bin,
    ]
    try:
        popen_options: dict[str, Any] = {
            "cwd": repo,
            "stdin": prompt,
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
            "close_fds": True,
            "start_new_session": True,
        }
        if _hold_fd is not None:
            popen_options["pass_fds"] = (_hold_fd,)
        worker = subprocess.Popen(worker_argv, **popen_options)
    except OSError as exc:
        prompt.close()
        return _write_terminal_result(
            run_dir,
            safe_id,
            "failed",
            error_type=type(exc).__name__,
            error_message=str(exc),
        )
    finally:
        if not prompt.closed:
            prompt.close()

    deadline = time.monotonic() + 2.0
    proc_info = _read_proc_stat(worker.pid)
    while proc_info is None and time.monotonic() < deadline:
        time.sleep(0.01)
        proc_info = _read_proc_stat(worker.pid)
    if proc_info is None:
        return _write_terminal_result(
            run_dir,
            safe_id,
            "failed",
            error_type="WorkerStartError",
            error_message="detached worker exited before registering its process identity",
        )

    metadata.update(
        {
            "pid": worker.pid,
            "pgid": worker.pid,
            "process_start_ticks": proc_info["start_ticks"],
            "lifecycle_status": "running",
        }
    )
    _atomic_json(run_dir / "metadata.json", metadata)
    _create_empty_file(run_dir / "launch.signal")
    return {
        "run_id": safe_id,
        "status": "running",
        "pid": worker.pid,
        "pgid": worker.pid,
        "run_dir": str(run_dir),
        "prompt_sha256": prompt_hash,
    }


def status_run(*, run_id: str, state_dir: str) -> dict[str, Any]:
    safe_id = _validate_run_id(run_id)
    try:
        run_dir = _run_dir(state_dir, safe_id)
        result = _read_optional_result(run_dir, safe_id)
        if result is not None:
            return result
        metadata = _metadata_for(run_dir, safe_id)
    except SessionError as exc:
        return {"run_id": safe_id, "status": "invalid", "error": str(exc)}

    state, supervisor_alive = _group_state(metadata)
    if state == "live":
        return {
            "run_id": safe_id,
            "status": "running",
            "pid": metadata["pid"],
            "pgid": metadata["pgid"],
            "supervisor_alive": supervisor_alive,
            "codex_version": metadata.get("codex_version"),
        }
    if state in {"invalid", "identity_mismatch", "unverifiable"}:
        return {
            "run_id": safe_id,
            "status": "invalid",
            "reason": f"cannot verify managed process identity ({state})",
        }
    return {
        "run_id": safe_id,
        "status": "stale",
        "reason": "managed process group exited without a terminal result",
    }


def tail_run(
    *,
    run_id: str,
    state_dir: str,
    stream: str,
    max_bytes: int = 8192,
    max_lines: int = 100,
) -> dict[str, Any]:
    safe_id = _validate_run_id(run_id)
    if stream not in _VALID_STREAMS:
        raise SessionError("stream must be stdout or stderr")
    if not 1 <= max_bytes <= _MAX_TAIL_BYTES:
        raise SessionError(f"max_bytes must be between 1 and {_MAX_TAIL_BYTES}")
    if not 1 <= max_lines <= _MAX_TAIL_LINES:
        raise SessionError(f"max_lines must be between 1 and {_MAX_TAIL_LINES}")
    run_dir = _run_dir(state_dir, safe_id)
    _metadata_for(run_dir, safe_id)
    log_path = run_dir / _VALID_STREAMS[stream]
    if log_path.is_symlink():
        raise SessionError("log file must not be a symlink")
    try:
        with log_path.open("rb") as log:
            log.seek(0, os.SEEK_END)
            size = log.tell()
            start = max(0, size - max_bytes)
            log.seek(start)
            data = log.read(max_bytes)
    except OSError as exc:
        raise SessionError(f"cannot read {stream} log") from exc
    lines = data.decode("utf-8", errors="replace").splitlines()
    content = "\n".join(lines[-max_lines:])
    return {
        "run_id": safe_id,
        "stream": stream,
        "content": content,
        "bytes_read": len(data),
        "truncated": start > 0 or len(lines) > max_lines,
    }


def _write_termination_state(run_dir: Path, **values: Any) -> None:
    current: dict[str, Any] = {}
    path = run_dir / "termination.json"
    if path.exists():
        try:
            current = _read_json(path)
        except SessionError:
            current = {}
    current.update(values)
    _atomic_json(path, current)


def terminate_run(
    *,
    run_id: str,
    state_dir: str,
    grace_seconds: float = 3.0,
) -> dict[str, Any]:
    safe_id = _validate_run_id(run_id)
    if not 0.0 <= grace_seconds <= 30.0:
        raise SessionError("grace_seconds must be between 0 and 30")
    run_dir = _run_dir(state_dir, safe_id)
    result = _read_optional_result(run_dir, safe_id)
    if result is not None:
        return result
    metadata = _metadata_for(run_dir, safe_id)
    state, _ = _group_state(metadata)
    if state == "dead":
        return status_run(run_id=safe_id, state_dir=state_dir)
    if state != "live":
        return {
            "run_id": safe_id,
            "status": "invalid",
            "reason": f"cannot terminate managed process group ({state})",
        }

    _write_termination_state(
        run_dir,
        run_id=safe_id,
        requested_at=_utc_now(),
        grace_seconds=grace_seconds,
        outcome="sigterm_requested",
    )
    pgid = int(metadata["pgid"])
    try:
        os.killpg(pgid, signal.SIGTERM)
    except ProcessLookupError:
        result = _read_optional_result(run_dir, safe_id)
        if result is not None:
            return result
        return status_run(run_id=safe_id, state_dir=state_dir)

    deadline = time.monotonic() + grace_seconds
    while time.monotonic() < deadline:
        result = _read_optional_result(run_dir, safe_id)
        if result is not None:
            _write_termination_state(run_dir, outcome="sigterm_completed")
            return result
        state, _ = _group_state(metadata)
        if state == "dead":
            break
        if state in {"invalid", "identity_mismatch", "unverifiable"}:
            return {
                "run_id": safe_id,
                "status": "invalid",
                "reason": f"managed process identity changed during termination ({state})",
            }
        time.sleep(0.05)

    state, _ = _group_state(metadata)
    if state == "live":
        _write_termination_state(run_dir, escalation_at=_utc_now(), outcome="sigkill_requested")
        try:
            os.killpg(pgid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            state, _ = _group_state(metadata)
            if state == "dead":
                break
            time.sleep(0.05)

    result = _read_optional_result(run_dir, safe_id)
    state, _ = _group_state(metadata)
    if result is not None:
        if state == "dead":
            _write_termination_state(run_dir, outcome="worker_recorded_terminal_result")
        return result
    if state == "dead":
        _write_termination_state(run_dir, outcome="sigkill_completed")
        return _write_terminal_result(
            run_dir,
            safe_id,
            "terminated",
            termination_outcome="sigkill",
        )
    _write_termination_state(run_dir, outcome="process_group_still_alive")
    return {
        "run_id": safe_id,
        "status": "running",
        "pid": metadata["pid"],
        "pgid": metadata["pgid"],
        "termination_outcome": "process_group_still_alive",
    }


def _worker_signal_handler(_signum: int, _frame: Any) -> None:
    global _termination_requested
    _termination_requested = True


def _worker_main(*, run_dir: Path, repo_path: str, codex_bin: str) -> int:
    global _termination_requested
    signal.signal(signal.SIGTERM, _worker_signal_handler)
    run_id = run_dir.name
    gate = run_dir / "launch.signal"
    deadline = time.monotonic() + _WORKER_GATE_TIMEOUT_SECONDS
    while not gate.exists() and time.monotonic() < deadline and not _termination_requested:
        time.sleep(0.02)

    if _termination_requested:
        _write_terminal_result(
            run_dir,
            run_id,
            "terminated",
            termination_outcome="sigterm_before_launch",
        )
        return 0
    if not gate.exists():
        _write_terminal_result(
            run_dir,
            run_id,
            "failed",
            error_type="StartHandshakeTimeout",
            error_message="launcher did not complete the detached worker handshake",
        )
        return 1

    try:
        metadata = _metadata_for(run_dir, run_id)
        proc_info = _read_proc_stat(os.getpid())
        if (
            proc_info is None
            or metadata.get("pid") != os.getpid()
            or metadata.get("pgid") != os.getpgrp()
            or metadata.get("process_start_ticks") != proc_info["start_ticks"]
        ):
            raise SessionError("detached worker identity does not match metadata")

        if _termination_requested:
            _write_terminal_result(
                run_dir,
                run_id,
                "terminated",
                termination_outcome="sigterm_before_codex_start",
            )
            return 0

        argv = [codex_bin, "exec", "--json", "--full-auto", "-"]
        with (run_dir / "stdout.jsonl").open("ab", buffering=0) as stdout_log:
            with (run_dir / "stderr.log").open("ab", buffering=0) as stderr_log:
                codex = subprocess.Popen(
                    argv,
                    cwd=repo_path,
                    stdin=sys.stdin.buffer,
                    stdout=stdout_log,
                    stderr=stderr_log,
                    close_fds=True,
                )
                exit_code = codex.wait()
        if _termination_requested:
            _write_terminal_result(
                run_dir,
                run_id,
                "terminated",
                exit_code=exit_code,
                termination_outcome="sigterm",
            )
        else:
            _write_terminal_result(
                run_dir,
                run_id,
                "completed",
                exit_code=exit_code,
            )
        return 0
    except Exception as exc:
        _write_terminal_result(
            run_dir,
            run_id,
            "failed",
            error_type=type(exc).__name__,
            error_message=str(exc),
        )
        return 1


def _worker_entry(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--repo-path", required=True)
    parser.add_argument("--codex-bin", required=True)
    args = parser.parse_args(argv)
    return _worker_main(
        run_dir=Path(args.run_dir),
        repo_path=args.repo_path,
        codex_bin=args.codex_bin,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="operation", required=True)

    start = commands.add_parser("start", help="launch one durable Codex session")
    start.add_argument("--run-id", required=True)
    start.add_argument("--repo", required=True)
    start.add_argument("--prompt-file", required=True)
    start.add_argument("--state-dir", required=True)
    start.add_argument("--codex-bin", default="codex")

    status = commands.add_parser("status", help="inspect durable session state")
    status.add_argument("--run-id", required=True)
    status.add_argument("--state-dir", required=True)

    tail = commands.add_parser("tail", help="read a bounded part of a session log")
    tail.add_argument("--run-id", required=True)
    tail.add_argument("--state-dir", required=True)
    tail.add_argument("--stream", choices=sorted(_VALID_STREAMS), default="stdout")
    tail.add_argument("--max-bytes", type=int, default=8192)
    tail.add_argument("--max-lines", type=int, default=100)

    terminate = commands.add_parser("terminate", help="terminate one named session")
    terminate.add_argument("--run-id", required=True)
    terminate.add_argument("--state-dir", required=True)
    terminate.add_argument("--grace-seconds", type=float, default=3.0)
    return parser


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    if argv and argv[0] == "_worker":
        return _worker_entry(argv[1:])

    parser = _parser()
    args = parser.parse_args(argv)
    try:
        if args.operation == "start":
            result = start_run(
                run_id=args.run_id,
                repo_path=args.repo,
                prompt_file=args.prompt_file,
                state_dir=args.state_dir,
                codex_bin=args.codex_bin,
            )
        elif args.operation == "status":
            result = status_run(run_id=args.run_id, state_dir=args.state_dir)
        elif args.operation == "tail":
            result = tail_run(
                run_id=args.run_id,
                state_dir=args.state_dir,
                stream=args.stream,
                max_bytes=args.max_bytes,
                max_lines=args.max_lines,
            )
        else:
            result = terminate_run(
                run_id=args.run_id,
                state_dir=args.state_dir,
                grace_seconds=args.grace_seconds,
            )
    except SessionError as exc:
        print(json.dumps({"status": "invalid", "error": str(exc)}, sort_keys=True))
        return 2

    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    if result.get("status") in {"invalid", "stale", "failed"}:
        return 1
    if args.operation == "terminate" and result.get("status") == "running":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
