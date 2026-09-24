#!/usr/bin/env python3
"""Supervise the repository's fixed canonical Just verification sequence."""

from __future__ import annotations

import argparse
import datetime as dt
import fcntl
import hashlib
import json
import os
import re
import selectors
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

try:
    from tools.agent.codex_session import _group_state, _read_proc_stat
except ModuleNotFoundError:  # Direct script execution sets sys.path to tools/agent.
    from codex_session import _group_state, _read_proc_stat

CANONICAL_RECIPES = (
    "check",
    "migration-check",
    "corpus-check",
    "scenario-check",
    "scenario-eval",
    "retrieval-eval",
    "provider-contract",
)
DEFAULT_TIMEOUT_SECONDS = 3600.0
MAX_TIMEOUT_SECONDS = 86400.0
MAX_LOG_BYTES = 1024 * 1024
_TERMINATION_GRACE_SECONDS = 0.4
_STARTUP_TIMEOUT_SECONDS = 10.0
_RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_SHA_RE = re.compile(r"^[0-9a-f]{40,64}$")
_TERMINAL_STATUSES = {"passed", "failed", "timed_out", "head_changed", "internal_error"}
_LOG_TRUNCATION_MARKER = b"\n... output truncated; showing start and end ...\n"


class VerifierError(Exception):
    """An expected validation or verifier lifecycle error."""


def _utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )


def _valid_sha(value: Any) -> bool:
    return isinstance(value, str) and bool(_SHA_RE.fullmatch(value))


def _valid_timeout(value: float | int) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise VerifierError("timeout must be a finite positive number of seconds")
    seconds = float(value)
    if not 0 < seconds <= MAX_TIMEOUT_SECONDS:
        raise VerifierError(
            f"timeout must be greater than 0 and no more than {MAX_TIMEOUT_SECONDS:g} seconds"
        )
    return seconds


def _recipes_digest(recipes: tuple[str, ...] | list[str]) -> str:
    data = json.dumps(list(recipes), ensure_ascii=False, separators=(",", ":")).encode()
    return hashlib.sha256(data).hexdigest()


def _fsync_directory(directory: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    fd = os.open(directory, flags)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
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


def _read_json(path: Path) -> dict[str, Any]:
    if path.is_symlink():
        raise VerifierError(f"{path.name} must not be a symlink")
    try:
        with path.open("r", encoding="utf-8") as stream:
            value = json.load(stream)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise VerifierError(f"cannot read valid {path.name}") from exc
    if not isinstance(value, dict):
        raise VerifierError(f"{path.name} must contain a JSON object")
    return value


def _assert_state_outside_repo(state: Path, repo: Path) -> None:
    try:
        state.relative_to(repo)
    except ValueError:
        return
    raise VerifierError("run-state directory must be outside the repository worktree")


def _resolve_repo_and_state(repo_path: str, state_dir: str) -> tuple[Path, Path]:
    repo = Path(repo_path).expanduser().resolve()
    requested_state = Path(state_dir).expanduser()
    if requested_state.is_symlink():
        raise VerifierError("run-state directory must not be a symlink")
    state = requested_state.resolve()
    if not repo.is_dir():
        raise VerifierError("repository path must be an existing directory")
    try:
        root_result = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "--show-toplevel"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise VerifierError("repository path is not a readable Git worktree") from exc
    if root_result.returncode or Path(root_result.stdout.decode("utf-8", errors="replace").strip()).resolve() != repo:
        raise VerifierError("repository path must name the Git worktree root")
    _assert_state_outside_repo(state, repo)
    if state == state.parent or not _RUN_ID_RE.fullmatch(state.name) or state.name in {".", ".."}:
        raise VerifierError("run-state directory must have a safe unique final path component")
    return repo, state


def _state_dir_for_status(state_dir: str) -> Path:
    requested = Path(state_dir).expanduser()
    if requested.is_symlink():
        raise VerifierError("run-state directory must not be a symlink")
    state = requested.resolve()
    if not state.is_dir():
        raise VerifierError("run-state directory does not exist")
    if not _RUN_ID_RE.fullmatch(state.name) or state.name in {".", ".."}:
        raise VerifierError("run-state directory name is invalid")
    return state


def _git_head(repo: Path) -> str:
    environment = os.environ.copy()
    environment["GIT_OPTIONAL_LOCKS"] = "0"
    environment["GIT_TERMINAL_PROMPT"] = "0"
    try:
        result = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "--verify", "HEAD"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=10,
            env=environment,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise VerifierError("cannot inspect repository HEAD") from exc
    if result.returncode:
        raise VerifierError("repository has no readable HEAD")
    head = result.stdout.decode("ascii", errors="replace").strip()
    if not _valid_sha(head):
        raise VerifierError("repository HEAD is not a valid commit SHA")
    return head


def _find_just() -> str:
    just = shutil.which("just")
    if not just:
        raise VerifierError("cannot find the just executable on PATH")
    return str(Path(just).resolve())


def _lock_path(repo: Path) -> Path:
    lock_root = Path.home() / ".local" / "state" / "ah-there-it-is" / "canonical-verifier-locks"
    try:
        lock_root.resolve().relative_to(repo)
    except ValueError:
        pass
    else:
        raise VerifierError("verifier lock directory must be outside the repository")
    if lock_root.is_symlink():
        raise VerifierError("verifier lock directory must not be a symlink")
    lock_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    if lock_root.is_symlink():
        raise VerifierError("verifier lock directory must not be a symlink")
    digest = hashlib.sha256(str(repo).encode("utf-8")).hexdigest()
    return lock_root / f"{digest}.lock"


def _lock_owner(fd: int) -> dict[str, Any] | None:
    try:
        os.lseek(fd, 0, os.SEEK_SET)
        data = os.read(fd, 65536)
        value = json.loads(data.decode("utf-8")) if data else None
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _write_lock_owner(fd: int, payload: dict[str, Any]) -> None:
    data = (json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n").encode()
    os.lseek(fd, 0, os.SEEK_SET)
    os.ftruncate(fd, 0)
    offset = 0
    while offset < len(data):
        offset += os.write(fd, data[offset:])
    os.fsync(fd)


def _acquire_repo_lock(repo: Path) -> tuple[int | None, dict[str, Any] | None]:
    path = _lock_path(repo)
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags, 0o600)
    except OSError as exc:
        raise VerifierError("cannot open verifier lock file") from exc
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        owner = _lock_owner(fd)
        os.close(fd)
        return None, owner
    except OSError as exc:
        os.close(fd)
        raise VerifierError("cannot acquire verifier lock") from exc
    return fd, None


def _write_state(state_dir: Path, state: dict[str, Any]) -> None:
    state["updated_at"] = _utc_now()
    _atomic_json(state_dir / "run.json", state)


def _validate_state(state_dir: Path, state: dict[str, Any]) -> None:
    required = {
        "schema_version",
        "run_id",
        "repo_path",
        "state_dir",
        "head_sha",
        "recipes",
        "recipe_definitions_sha256",
        "just_path",
        "timeout_seconds",
        "status",
        "started_at",
        "updated_at",
        "next_index",
        "checks",
        "attempts",
        "active_command",
        "resume_count",
    }
    if not required.issubset(state):
        raise VerifierError("run.json is missing required fields")
    schema_version = state.get("schema_version")
    if not isinstance(schema_version, int) or isinstance(schema_version, bool) or schema_version != 1:
        raise VerifierError("run.json schema version is invalid")
    if state.get("run_id") != state_dir.name:
        raise VerifierError("run.json identity does not match its state directory")
    if (
        not isinstance(state.get("repo_path"), str)
        or not state["repo_path"]
        or "\x00" in state["repo_path"]
    ):
        raise VerifierError("run.json repository path is invalid")
    if not isinstance(state.get("state_dir"), str) or "\x00" in state["state_dir"]:
        raise VerifierError("run.json state directory identity is invalid")
    if Path(state["state_dir"]).resolve() != state_dir:
        raise VerifierError("run.json state directory identity is invalid")
    if not _valid_sha(state.get("head_sha")):
        raise VerifierError("run.json Git HEAD is invalid")
    recipes = state.get("recipes")
    if (
        not isinstance(recipes, list)
        or not recipes
        or any(not isinstance(recipe, str) for recipe in recipes)
    ):
        raise VerifierError("run.json command definitions are invalid")
    if not _valid_sha(state.get("recipe_definitions_sha256")):
        raise VerifierError("run.json command definition digest is invalid")
    if (
        not isinstance(state.get("just_path"), str)
        or not state["just_path"]
        or "\x00" in state["just_path"]
    ):
        raise VerifierError("run.json Just executable is invalid")
    try:
        _valid_timeout(state.get("timeout_seconds"))
    except VerifierError as exc:
        raise VerifierError("run.json timeout is invalid") from exc
    allowed_states = {"starting", "running", "interrupted", *_TERMINAL_STATUSES}
    if not isinstance(state.get("status"), str) or state["status"] not in allowed_states:
        raise VerifierError("run.json status is invalid")
    for field in ("started_at", "updated_at"):
        if not isinstance(state.get(field), str) or not state[field]:
            raise VerifierError(f"run.json {field} is invalid")
    next_index = state.get("next_index")
    checks = state.get("checks")
    if (
        not isinstance(next_index, int)
        or isinstance(next_index, bool)
        or not isinstance(checks, list)
        or next_index != len(checks)
        or next_index > len(recipes)
    ):
        raise VerifierError("run.json completed-check index is invalid")
    for index, check in enumerate(checks):
        if (
            not isinstance(check, dict)
            or not isinstance(check.get("index"), int)
            or isinstance(check.get("index"), bool)
            or check.get("index") != index
            or check.get("recipe") != recipes[index]
            or check.get("head_sha") != state["head_sha"]
            or not isinstance(check.get("status"), str)
            or check.get("status") not in {"success", "failed", "timed_out"}
        ):
            raise VerifierError("run.json contains an invalid check result")
    attempts = state.get("attempts")
    if (
        not isinstance(attempts, list)
        or len(attempts) != len(recipes)
        or any(not isinstance(count, int) or isinstance(count, bool) or count < 0 for count in attempts)
    ):
        raise VerifierError("run.json attempt counters are invalid")
    active = state.get("active_command")
    if active is not None:
        if (
            not isinstance(active, dict)
            or active.get("index") != next_index
            or next_index >= len(recipes)
            or active.get("recipe") != recipes[next_index]
            or active.get("attempt") != attempts[next_index]
        ):
            raise VerifierError("run.json active command is invalid")
        for key in ("pid", "pgid", "process_start_ticks"):
            value = active.get(key)
            if value is not None and (not isinstance(value, int) or isinstance(value, bool) or value <= 0):
                raise VerifierError("run.json active process identity is invalid")
    for process_record in (state, active):
        if process_record is None:
            continue
        process_values = [process_record.get(key) for key in ("pid", "pgid", "process_start_ticks")]
        if any(value is not None for value in process_values) and any(value is None for value in process_values):
            raise VerifierError("run.json process identity is incomplete")
        for value in process_values:
            if value is not None and (
                not isinstance(value, int) or isinstance(value, bool) or value <= 0
            ):
                raise VerifierError("run.json process identity is invalid")
    resume_count = state.get("resume_count")
    if not isinstance(resume_count, int) or isinstance(resume_count, bool) or resume_count < 0:
        raise VerifierError("run.json resume count is invalid")


def _read_state(state_dir: Path) -> dict[str, Any]:
    state = _read_json(state_dir / "run.json")
    _validate_state(state_dir, state)
    return state


def _initial_state(
    *,
    repo: Path,
    state_dir: Path,
    head_sha: str,
    just_path: str,
    timeout_seconds: float,
) -> dict[str, Any]:
    now = _utc_now()
    recipes = list(CANONICAL_RECIPES)
    return {
        "schema_version": 1,
        "run_id": state_dir.name,
        "repo_path": str(repo),
        "state_dir": str(state_dir),
        "head_sha": head_sha,
        "recipes": recipes,
        "recipe_definitions_sha256": _recipes_digest(recipes),
        "just_path": just_path,
        "timeout_seconds": timeout_seconds,
        "status": "starting",
        "started_at": now,
        "updated_at": now,
        "next_index": 0,
        "checks": [],
        "attempts": [0 for _ in recipes],
        "active_command": None,
        "resume_count": 0,
        "pid": None,
        "pgid": None,
        "process_start_ticks": None,
    }


def _process_state(record: dict[str, Any] | None) -> tuple[str, bool]:
    if not isinstance(record, dict):
        return "unknown", False
    try:
        pid = record.get("pid")
        pgid = record.get("pgid")
        start_ticks = record.get("process_start_ticks")
        if any(value is None for value in (pid, pgid, start_ticks)):
            return "unknown", False
        metadata = {
            "pid": int(pid),
            "pgid": int(pgid),
            "process_start_ticks": int(start_ticks),
        }
    except (TypeError, ValueError):
        return "invalid", False
    return _group_state(metadata)


def _summary_if_present(
    state_dir: Path,
    run_id: str,
    state: dict[str, Any],
) -> dict[str, Any] | None:
    path = state_dir / "summary.json"
    if not path.exists() and not path.is_symlink():
        return None
    summary = _read_json(path)
    schema_version = summary.get("schema_version")
    if (
        not isinstance(schema_version, int)
        or isinstance(schema_version, bool)
        or schema_version != 1
        or summary.get("run_id") != run_id
    ):
        raise VerifierError("summary.json identity or schema is invalid")
    if not isinstance(summary.get("status"), str) or summary.get("status") not in _TERMINAL_STATUSES:
        raise VerifierError("summary.json status is invalid")
    if summary.get("head_sha") != state.get("head_sha"):
        raise VerifierError("summary.json Git HEAD differs from run state")
    if summary.get("recipes") != state.get("recipes"):
        raise VerifierError("summary.json command definitions differ from run state")
    if summary.get("recipe_definitions_sha256") != state.get("recipe_definitions_sha256"):
        raise VerifierError("summary.json command definition digest differs from run state")
    if summary.get("checks") != state.get("checks"):
        raise VerifierError("summary.json check results differ from run state")
    if not isinstance(summary.get("checks"), list):
        raise VerifierError("summary.json has no check results")
    if summary["status"] == "passed" and (
        len(summary["checks"]) != len(CANONICAL_RECIPES)
        or any(check.get("status") != "success" for check in summary["checks"] if isinstance(check, dict))
    ):
        raise VerifierError("passed summary does not contain the complete successful recipe set")
    if not isinstance(summary.get("finished_at"), str) or not summary["finished_at"]:
        raise VerifierError("summary.json finish timestamp is invalid")
    return summary


def _resume_reasons(state: dict[str, Any], repo: Path) -> list[str]:
    reasons: list[str] = []
    if tuple(state["recipes"]) != CANONICAL_RECIPES:
        reasons.append("stored Just recipes differ from the fixed canonical sequence")
    if state["recipe_definitions_sha256"] != _recipes_digest(CANONICAL_RECIPES):
        reasons.append("stored canonical command definition digest differs")
    try:
        current_head = _git_head(repo)
    except (VerifierError, OSError, ValueError) as exc:
        reasons.append(str(exc))
    else:
        if current_head != state["head_sha"]:
            reasons.append(
                f"Git HEAD changed from {state['head_sha']} to {current_head}"
            )
    if state["next_index"] != len(state["checks"]):
        reasons.append("completed-check index does not match durable results")
    for index, check in enumerate(state["checks"]):
        if (
            check.get("status") != "success"
            or check.get("recipe") != CANONICAL_RECIPES[index]
            or check.get("head_sha") != state["head_sha"]
        ):
            reasons.append(f"completed check {index + 1} did not succeed on the recorded HEAD")
            break
    if state.get("status") in _TERMINAL_STATUSES:
        reasons.append("terminal verification runs cannot be resumed")
    return reasons


def _active_owner_result(owner: dict[str, Any] | None) -> dict[str, Any]:
    return {
        "status": "already_running",
        "message": "another canonical verifier currently holds the repository lock",
        "active_run": owner,
    }


def _launch_worker(run_dir: Path, lock_fd: int) -> dict[str, Any]:
    read_fd, write_fd = os.pipe()
    argv = [
        sys.executable,
        str(Path(__file__).resolve()),
        "_worker",
        "--state-dir",
        str(run_dir),
        "--lock-fd",
        str(lock_fd),
        "--ready-fd",
        str(write_fd),
    ]
    try:
        worker = subprocess.Popen(
            argv,
            cwd=run_dir,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            pass_fds=(lock_fd, write_fd),
            start_new_session=True,
        )
    except OSError as exc:
        os.close(read_fd)
        os.close(write_fd)
        raise VerifierError("cannot start detached canonical verifier") from exc
    finally:
        try:
            os.close(write_fd)
        except OSError:
            pass
        try:
            os.close(lock_fd)
        except OSError:
            pass

    try:
        import select

        ready, _, _ = select.select([read_fd], [], [], _STARTUP_TIMEOUT_SECONDS)
        signal_byte = os.read(read_fd, 1) if ready else b""
    finally:
        os.close(read_fd)
    if signal_byte == b"R":
        state = _read_state(run_dir)
        return {
            "status": "running",
            "run_id": state["run_id"],
            "repo_path": state["repo_path"],
            "state_dir": str(run_dir),
            "head_sha": state["head_sha"],
            "pid": state["pid"],
            "current_recipe": (
                state["active_command"]["recipe"] if state["active_command"] else None
            ),
        }
    current = status_run(state_dir=str(run_dir))
    if current.get("status") in {"running", "starting", "orphaned_command"}:
        return current
    return {
        "status": "interrupted",
        "run_id": run_dir.name,
        "state_dir": str(run_dir),
        "worker_pid": worker.pid,
        "reason": "detached verifier did not complete its startup handshake",
        "state": current,
    }


def start_run(
    *,
    repo_path: str,
    state_dir: str,
    timeout_seconds: float | None = None,
) -> dict[str, Any]:
    if os.name != "posix":
        raise VerifierError("canonical verifier supports POSIX hosts only")
    repo, run_dir = _resolve_repo_and_state(repo_path, state_dir)
    timeout = _valid_timeout(
        DEFAULT_TIMEOUT_SECONDS if timeout_seconds is None else timeout_seconds
    )
    just_path = _find_just()
    if run_dir.exists():
        if not run_dir.is_dir():
            raise VerifierError("run-state path already exists and is not a directory")
        current = status_run(state_dir=str(run_dir))
        if current.get("status") in {"running", "starting", "orphaned_command"}:
            return {**current, "status": "already_running"}
        raise VerifierError("run-state directories are unique and cannot be reused")

    lock_fd, owner = _acquire_repo_lock(repo)
    if lock_fd is None:
        return _active_owner_result(owner)
    created = False
    try:
        previous_owner = _lock_owner(lock_fd)
        previous_state_dir = (
            previous_owner.get("state_dir") if isinstance(previous_owner, dict) else None
        )
        if isinstance(previous_state_dir, str) and Path(previous_state_dir).resolve() != run_dir:
            previous = status_run(state_dir=previous_state_dir)
            if previous.get("status") in {"running", "orphaned_command", "invalid"}:
                os.close(lock_fd)
                return _active_owner_result(
                    {"state_dir": previous_state_dir, "status": previous.get("status"), "state": previous}
                )
        if run_dir.exists():
            raise VerifierError("run-state directory already exists")
        run_dir.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        run_dir.mkdir(mode=0o700)
        created = True
        _fsync_directory(run_dir.parent)
        head = _git_head(repo)
        state = _initial_state(
            repo=repo,
            state_dir=run_dir,
            head_sha=head,
            just_path=just_path,
            timeout_seconds=timeout,
        )
        _write_state(run_dir, state)
        _write_lock_owner(
            lock_fd,
            {
                "run_id": run_dir.name,
                "repo_path": str(repo),
                "state_dir": str(run_dir),
                "head_sha": head,
                "started_at": state["started_at"],
            },
        )
        return _launch_worker(run_dir, lock_fd)
    except Exception:
        try:
            os.close(lock_fd)
        except OSError:
            pass
        if created:
            try:
                current = _read_state(run_dir)
            except VerifierError:
                current = None
            if current is not None:
                current["status"] = "internal_error"
                _write_state(run_dir, current)
                _write_summary(run_dir, current, "internal_error", error="verifier startup failed")
        raise


def _resume_blocked(reasons: list[str], state_dir: Path) -> dict[str, Any]:
    return {
        "status": "resume_blocked",
        "state_dir": str(state_dir),
        "reasons": reasons,
    }


def resume_run(
    *,
    repo_path: str,
    state_dir: str,
    timeout_seconds: float | None = None,
) -> dict[str, Any]:
    if os.name != "posix":
        raise VerifierError("canonical verifier supports POSIX hosts only")
    repo, run_dir = _resolve_repo_and_state(repo_path, state_dir)
    state = _read_state(run_dir)
    if Path(state["repo_path"]).resolve() != repo:
        raise VerifierError("run-state repository identity differs from the requested repository")
    current = status_run(state_dir=str(run_dir))
    if current.get("status") in {"running", "orphaned_command"}:
        return {**current, "status": "already_running"}
    if current.get("status") == "invalid":
        return _resume_blocked([current.get("reason", current.get("error", "prior process state is unverifiable"))], run_dir)
    if current.get("status") in _TERMINAL_STATUSES:
        return {"status": current["status"], "state_dir": str(run_dir), "summary": current.get("summary")}
    reasons = _resume_reasons(state, repo)
    if reasons:
        return _resume_blocked(reasons, run_dir)
    timeout = (
        state["timeout_seconds"]
        if timeout_seconds is None
        else _valid_timeout(timeout_seconds)
    )

    lock_fd, owner = _acquire_repo_lock(repo)
    if lock_fd is None:
        return _active_owner_result(owner)
    try:
        state = _read_state(run_dir)
        current = status_run(state_dir=str(run_dir))
        if current.get("status") in {"running", "orphaned_command"}:
            os.close(lock_fd)
            return {**current, "status": "already_running"}
        if current.get("status") == "invalid":
            os.close(lock_fd)
            return _resume_blocked([current.get("reason", current.get("error", "prior process state is unverifiable"))], run_dir)
        reasons = _resume_reasons(state, repo)
        if reasons:
            os.close(lock_fd)
            return _resume_blocked(reasons, run_dir)
        state["status"] = "starting"
        state["timeout_seconds"] = timeout
        state["resume_count"] += 1
        state["pid"] = None
        state["pgid"] = None
        state["process_start_ticks"] = None
        state["active_command"] = None
        _write_state(run_dir, state)
        _write_lock_owner(
            lock_fd,
            {
                "run_id": state["run_id"],
                "repo_path": str(repo),
                "state_dir": str(run_dir),
                "head_sha": state["head_sha"],
                "resumed_at": _utc_now(),
                "resume_count": state["resume_count"],
            },
        )
        return _launch_worker(run_dir, lock_fd)
    except Exception:
        try:
            os.close(lock_fd)
        except OSError:
            pass
        raise


def status_run(*, state_dir: str) -> dict[str, Any]:
    try:
        run_dir = _state_dir_for_status(state_dir)
        state = _read_state(run_dir)
        repo = Path(state["repo_path"]).resolve()
        if repo != Path(state["repo_path"]):
            raise VerifierError("run.json repository path is not canonical")
        _assert_state_outside_repo(run_dir, repo)
        summary = _summary_if_present(run_dir, run_dir.name, state)
        runner_state, runner_alive = _process_state(state)
        child_state, _child_leader_alive = _process_state(state.get("active_command"))
        if runner_state in {"invalid", "identity_mismatch", "unverifiable"}:
            if summary is not None:
                return {"status": summary["status"], "summary": summary, "state": state}
            return {
                "status": "invalid",
                "reason": f"cannot verify supervisor process identity ({runner_state})",
                "state_dir": str(run_dir),
            }
        if runner_alive or runner_state == "live":
            return {
                "status": "running",
                "run_id": state["run_id"],
                "state_dir": str(run_dir),
                "pid": state.get("pid"),
                "head_sha": state["head_sha"],
                "current_recipe": (
                    state["active_command"]["recipe"]
                    if isinstance(state.get("active_command"), dict)
                    else None
                ),
                "command_process_alive": child_state == "live",
                "resume_allowed": False,
                "summary": summary,
            }
        if child_state in {"invalid", "identity_mismatch", "unverifiable"}:
            if summary is not None:
                return {"status": summary["status"], "summary": summary, "state": state}
            return {
                "status": "invalid",
                "reason": f"cannot verify active Just process identity ({child_state})",
                "state_dir": str(run_dir),
            }
        if child_state == "live":
            return {
                "status": "orphaned_command",
                "run_id": state["run_id"],
                "state_dir": str(run_dir),
                "current_recipe": state.get("active_command", {}).get("recipe"),
                "active_command": state.get("active_command"),
                "resume_allowed": False,
                "reason": "the previous supervisor stopped while its Just process group is still alive",
            }
        if summary is not None:
            return {"status": summary["status"], "summary": summary, "state": state}
        if state.get("status") == "starting" and state.get("pid") is None:
            return {
                "status": "starting",
                "run_id": state["run_id"],
                "state_dir": str(run_dir),
                "resume_allowed": False,
            }
        reasons = _resume_reasons(state, repo)
        return {
            "status": "interrupted",
            "run_id": state["run_id"],
            "state_dir": str(run_dir),
            "head_sha": state["head_sha"],
            "completed_checks": len(state["checks"]),
            "next_recipe": (
                CANONICAL_RECIPES[state["next_index"]]
                if state["next_index"] < len(CANONICAL_RECIPES)
                else None
            ),
            "resume_allowed": not reasons,
            "resume_blockers": reasons,
            "state": state,
        }
    except (VerifierError, OSError, ValueError) as exc:
        return {"status": "invalid", "error": str(exc)}


class _BoundedLog:
    """Keep the beginning and end of each stream under one fixed size cap."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.partial_path = path.with_name(path.name + ".partial")
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0)
        self.fd = os.open(self.partial_path, flags, 0o600)
        _fsync_directory(path.parent)
        self.prefix_limit = MAX_LOG_BYTES // 2
        self.tail_limit = MAX_LOG_BYTES - self.prefix_limit
        self.prefix_bytes = 0
        self.bytes_seen = 0
        self.tail = bytearray()
        self.truncated = False

    def _write_all(self, data: bytes) -> None:
        view = memoryview(data)
        offset = 0
        while offset < len(view):
            offset += os.write(self.fd, view[offset:])

    def write(self, data: bytes) -> None:
        self.bytes_seen += len(data)
        prefix_room = self.prefix_limit - self.prefix_bytes
        if prefix_room > 0:
            prefix = data[:prefix_room]
            self._write_all(prefix)
            self.prefix_bytes += len(prefix)
            os.fsync(self.fd)
            data = data[len(prefix) :]
        if data:
            self.tail.extend(data)
            if len(self.tail) > self.tail_limit:
                del self.tail[: len(self.tail) - self.tail_limit]
        if self.bytes_seen > MAX_LOG_BYTES:
            self.truncated = True

    def finish(self) -> dict[str, Any]:
        os.fsync(self.fd)
        os.close(self.fd)
        self.fd = -1
        try:
            with self.partial_path.open("rb") as stream:
                prefix = stream.read(self.prefix_limit)
            if self.truncated:
                tail_room = MAX_LOG_BYTES - len(prefix) - len(_LOG_TRUNCATION_MARKER)
                content = prefix + _LOG_TRUNCATION_MARKER + bytes(self.tail[-tail_room:])
            else:
                content = prefix + bytes(self.tail)
            fd, temporary = tempfile.mkstemp(
                prefix=f".{self.path.name}.", suffix=".tmp", dir=self.path.parent
            )
            try:
                with os.fdopen(fd, "wb") as stream:
                    stream.write(content)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, self.path)
                _fsync_directory(self.path.parent)
            finally:
                try:
                    os.unlink(temporary)
                except FileNotFoundError:
                    pass
        finally:
            try:
                self.partial_path.unlink()
            except FileNotFoundError:
                pass
        return {
            "path": self.path.name,
            "bytes_seen": self.bytes_seen,
            "bytes_saved": len(content),
            "truncated": self.truncated,
        }

    def abort(self) -> None:
        if self.fd >= 0:
            try:
                os.fsync(self.fd)
            finally:
                os.close(self.fd)
                self.fd = -1


def _create_command_wrapper_state(
    state_dir: Path,
    *,
    index: int,
    recipe: str,
    attempt: int,
    pid: int,
    pgid: int,
    start_ticks: int,
) -> None:
    state = _read_state(state_dir)
    active = state.get("active_command")
    if (
        not isinstance(active, dict)
        or active.get("index") != index
        or active.get("recipe") != recipe
        or active.get("attempt") != attempt
    ):
        raise VerifierError("active Just command no longer matches run state")
    active.update({"pid": pid, "pgid": pgid, "process_start_ticks": start_ticks})
    state["active_command"] = active
    _write_state(state_dir, state)


def _command_entry(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--state-dir", required=True)
    parser.add_argument("--index", type=int, required=True)
    parser.add_argument("--recipe", required=True)
    parser.add_argument("--attempt", type=int, required=True)
    parser.add_argument("--just-path", required=True)
    parser.add_argument("--lock-fd", type=int, required=True)
    args = parser.parse_args(argv)
    try:
        run_dir = _state_dir_for_status(args.state_dir)
        process = _read_proc_stat(os.getpid())
        if process is None or process["pgrp"] != os.getpgrp():
            raise VerifierError("cannot record Just process identity")
        _create_command_wrapper_state(
            run_dir,
            index=args.index,
            recipe=args.recipe,
            attempt=args.attempt,
            pid=os.getpid(),
            pgid=os.getpgrp(),
            start_ticks=process["start_ticks"],
        )
        descriptor_flags = fcntl.fcntl(args.lock_fd, fcntl.F_GETFD)
        fcntl.fcntl(args.lock_fd, fcntl.F_SETFD, descriptor_flags | fcntl.FD_CLOEXEC)
        os.execvpe(args.just_path, [args.just_path, args.recipe], os.environ.copy())
    except Exception as exc:
        print(f"canonical verifier command launch failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 127
    return 0


def _signal_group(pgid: int, sig: int) -> None:
    try:
        os.killpg(pgid, sig)
    except ProcessLookupError:
        pass


def _execute_recipe(
    *,
    state_dir: Path,
    state: dict[str, Any],
    index: int,
    recipe: str,
    attempt: int,
    timeout_seconds: float,
    lock_fd: int,
) -> dict[str, Any]:
    stdout_path = state_dir / f"{index + 1:02d}-{recipe}-attempt-{attempt}.stdout.log"
    stderr_path = state_dir / f"{index + 1:02d}-{recipe}-attempt-{attempt}.stderr.log"
    stdout_log = _BoundedLog(stdout_path)
    try:
        stderr_log = _BoundedLog(stderr_path)
    except Exception:
        stdout_log.abort()
        raise

    started_at = _utc_now()
    start = time.monotonic()
    argv = [
        sys.executable,
        str(Path(__file__).resolve()),
        "_command",
        "--state-dir",
        str(state_dir),
        "--index",
        str(index),
        "--recipe",
        recipe,
        "--attempt",
        str(attempt),
        "--just-path",
        state["just_path"],
        "--lock-fd",
        str(lock_fd),
    ]
    process: subprocess.Popen[bytes] | None = None
    selector = selectors.DefaultSelector()
    registered: dict[int, _BoundedLog] = {}
    timed_out = False
    term_at: float | None = None
    kill_sent = False
    try:
        process = subprocess.Popen(
            argv,
            cwd=state["repo_path"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
            close_fds=True,
            pass_fds=(lock_fd,),
            start_new_session=True,
        )
        registration_deadline = time.monotonic() + 5.0
        while time.monotonic() < registration_deadline:
            latest = _read_state(state_dir)
            active = latest.get("active_command")
            if isinstance(active, dict) and active.get("pid") == process.pid:
                break
            if process.poll() is not None:
                break
            time.sleep(0.01)
        latest = _read_state(state_dir)
        active = latest.get("active_command")
        if (
            not isinstance(active, dict)
            or active.get("pid") != process.pid
            or active.get("pgid") != process.pid
        ):
            _signal_group(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=_TERMINATION_GRACE_SECONDS)
            except subprocess.TimeoutExpired:
                _signal_group(process.pid, signal.SIGKILL)
                process.wait(timeout=2.0)
            raise VerifierError("Just command process identity was not durably recorded")

        assert process.stdout is not None and process.stderr is not None
        for stream, sink in ((process.stdout, stdout_log), (process.stderr, stderr_log)):
            os.set_blocking(stream.fileno(), False)
            selector.register(stream, selectors.EVENT_READ, sink)
            registered[stream.fileno()] = sink

        deadline = start + timeout_seconds
        while True:
            now = time.monotonic()
            if not timed_out and now >= deadline:
                timed_out = True
                term_at = now
                _signal_group(process.pid, signal.SIGTERM)
            if timed_out and not kill_sent and term_at is not None and now >= term_at + _TERMINATION_GRACE_SECONDS:
                _signal_group(process.pid, signal.SIGKILL)
                kill_sent = True

            wait_for = 0.05
            if not timed_out:
                wait_for = max(0.0, min(wait_for, deadline - now))
            elif not kill_sent and term_at is not None:
                wait_for = max(0.0, min(wait_for, term_at + _TERMINATION_GRACE_SECONDS - now))
            if selector.get_map():
                events = selector.select(wait_for)
            else:
                time.sleep(wait_for)
                events = []
            for key, _ in events:
                stream = key.fileobj
                sink = key.data
                try:
                    chunk = os.read(stream.fileno(), 65536)
                except BlockingIOError:
                    continue
                if chunk:
                    sink.write(chunk)
                else:
                    selector.unregister(stream)
                    registered.pop(stream.fileno(), None)
                    stream.close()

            code = process.poll()
            if code is not None and not selector.get_map() and (not timed_out or kill_sent):
                break
            if timed_out and kill_sent and code is not None and not selector.get_map():
                break

        exit_code = process.wait(timeout=3.0)
    except Exception:
        if process is not None:
            _signal_group(process.pid, signal.SIGKILL)
            try:
                process.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                pass
        for stream in (process.stdout, process.stderr) if process is not None else ():
            if stream is not None:
                try:
                    selector.unregister(stream)
                except (KeyError, ValueError):
                    pass
                try:
                    stream.close()
                except OSError:
                    pass
        stdout_log.abort()
        stderr_log.abort()
        selector.close()
        raise

    selector.close()
    stdout_result = stdout_log.finish()
    stderr_result = stderr_log.finish()
    finished_at = _utc_now()
    status = "timed_out" if timed_out else ("success" if exit_code == 0 else "failed")
    return {
        "index": index,
        "recipe": recipe,
        "command": ["just", recipe],
        "attempt": attempt,
        "head_sha": state["head_sha"],
        "started_at": started_at,
        "finished_at": finished_at,
        "duration_seconds": round(time.monotonic() - start, 3),
        "exit_code": exit_code,
        "status": status,
        "timed_out": timed_out,
        "stdout": stdout_result,
        "stderr": stderr_result,
    }


def _write_summary(
    state_dir: Path,
    state: dict[str, Any],
    status: str,
    *,
    error: str | None = None,
    observed_head: str | None = None,
) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "schema_version": 1,
        "run_id": state["run_id"],
        "status": status,
        "repo_path": state["repo_path"],
        "state_dir": str(state_dir),
        "head_sha": state["head_sha"],
        "recipes": state["recipes"],
        "recipe_definitions_sha256": state["recipe_definitions_sha256"],
        "timeout_seconds": state["timeout_seconds"],
        "started_at": state["started_at"],
        "finished_at": _utc_now(),
        "duration_seconds": round(
            sum(float(check.get("duration_seconds", 0.0)) for check in state["checks"]),
            3,
        ),
        "checks": state["checks"],
    }
    if error is not None:
        summary["error"] = " ".join(error.split())[:500]
    if observed_head is not None:
        summary["observed_head"] = observed_head
    if state["checks"] and state["checks"][-1]["status"] != "success":
        summary["failed_recipe"] = state["checks"][-1]["recipe"]
        summary["exit_code"] = state["checks"][-1]["exit_code"]
    _atomic_json(state_dir / "summary.json", summary)
    state["status"] = status
    state["active_command"] = None
    _write_state(state_dir, state)
    return summary


def _run_checks(state_dir: Path, lock_fd: int) -> int:
    state = _read_state(state_dir)
    repo = Path(state["repo_path"])
    try:
        while state["next_index"] < len(CANONICAL_RECIPES):
            index = state["next_index"]
            recipe = CANONICAL_RECIPES[index]
            try:
                before = _git_head(repo)
            except VerifierError as exc:
                _write_summary(state_dir, state, "head_changed", error=str(exc))
                return 1
            if before != state["head_sha"]:
                _write_summary(state_dir, state, "head_changed", observed_head=before)
                return 1

            state["attempts"][index] += 1
            attempt = state["attempts"][index]
            state["active_command"] = {
                "index": index,
                "recipe": recipe,
                "attempt": attempt,
                "started_at": _utc_now(),
                "pid": None,
                "pgid": None,
                "process_start_ticks": None,
            }
            state["status"] = "running"
            _write_state(state_dir, state)
            result = _execute_recipe(
                state_dir=state_dir,
                state=state,
                index=index,
                recipe=recipe,
                attempt=attempt,
                timeout_seconds=state["timeout_seconds"],
                lock_fd=lock_fd,
            )
            state = _read_state(state_dir)
            state["active_command"] = None
            state["checks"].append(result)
            state["next_index"] = index + 1
            _write_state(state_dir, state)
            if result["status"] != "success":
                final_status = "timed_out" if result["status"] == "timed_out" else "failed"
                _write_summary(state_dir, state, final_status)
                return 1

            try:
                after = _git_head(repo)
            except VerifierError as exc:
                _write_summary(state_dir, state, "head_changed", error=str(exc))
                return 1
            if after != state["head_sha"]:
                _write_summary(state_dir, state, "head_changed", observed_head=after)
                return 1

        _write_summary(state_dir, state, "passed")
        return 0
    except Exception as exc:
        try:
            state = _read_state(state_dir)
            state["active_command"] = None
            _write_summary(
                state_dir,
                state,
                "internal_error",
                error=f"{type(exc).__name__}: {exc}",
            )
        except Exception:
            pass
        return 1


def _worker_main(*, state_dir: Path, lock_fd: int, ready_fd: int) -> int:
    try:
        state = _read_state(state_dir)
        process = _read_proc_stat(os.getpid())
        if process is None or process["pgrp"] != os.getpgrp() or os.getpgrp() != os.getpid():
            raise VerifierError("detached supervisor process identity is invalid")
        state["pid"] = os.getpid()
        state["pgid"] = os.getpgrp()
        state["process_start_ticks"] = process["start_ticks"]
        state["status"] = "running"
        _write_state(state_dir, state)
        os.write(ready_fd, b"R")
    except Exception as exc:
        try:
            os.write(ready_fd, b"E")
        except OSError:
            pass
        try:
            state = _read_state(state_dir)
            _write_summary(
                state_dir,
                state,
                "internal_error",
                error=f"{type(exc).__name__}: {exc}",
            )
        except Exception:
            pass
        os.close(ready_fd)
        os.close(lock_fd)
        return 1
    os.close(ready_fd)
    try:
        return _run_checks(state_dir, lock_fd)
    finally:
        try:
            os.close(lock_fd)
        except OSError:
            pass


def _worker_entry(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--state-dir", required=True)
    parser.add_argument("--lock-fd", type=int, required=True)
    parser.add_argument("--ready-fd", type=int, required=True)
    args = parser.parse_args(argv)
    return _worker_main(
        state_dir=Path(args.state_dir),
        lock_fd=args.lock_fd,
        ready_fd=args.ready_fd,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="operation", required=True)

    start = commands.add_parser("start", help="start one canonical verification run")
    start.add_argument("--repo", required=True)
    start.add_argument("--state-dir", required=True)
    start.add_argument("--timeout-seconds", type=float)

    status = commands.add_parser("status", help="inspect one verification run")
    status.add_argument("--state-dir", required=True)

    resume = commands.add_parser("resume", help="resume an interrupted same-HEAD run")
    resume.add_argument("--repo", required=True)
    resume.add_argument("--state-dir", required=True)
    resume.add_argument("--timeout-seconds", type=float)
    return parser


def main(argv: list[str] | None = None) -> int:
    values = sys.argv[1:] if argv is None else argv
    if values and values[0] == "_worker":
        return _worker_entry(values[1:])
    if values and values[0] == "_command":
        return _command_entry(values[1:])
    parser = _parser()
    args = parser.parse_args(values)
    try:
        if args.operation == "start":
            result = start_run(
                repo_path=args.repo,
                state_dir=args.state_dir,
                timeout_seconds=args.timeout_seconds,
            )
        elif args.operation == "status":
            result = status_run(state_dir=args.state_dir)
        else:
            result = resume_run(
                repo_path=args.repo,
                state_dir=args.state_dir,
                timeout_seconds=args.timeout_seconds,
            )
    except (VerifierError, OSError, ValueError) as exc:
        print(json.dumps({"status": "invalid", "error": str(exc)}, sort_keys=True))
        return 2

    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    if result.get("status") in {"failed", "timed_out", "head_changed", "internal_error", "resume_blocked", "invalid", "interrupted", "orphaned_command"}:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
