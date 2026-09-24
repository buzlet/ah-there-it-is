#!/usr/bin/env python3
"""Wait for checks on one exact GitHub pull-request head without changing CI state."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Callable

_SHA_RE = re.compile(r"^[0-9a-fA-F]{40,64}$")
_REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_TERMINAL_SUCCESS = {"success", "neutral", "skipped"}
_CHECK_RUN_PENDING = {"queued", "in_progress", "pending"}
_STATUS_VALUES = {"pending", "success", "failure", "error"}
_DEFAULT_TIMEOUT_SECONDS = 1800.0
_DEFAULT_POLL_SECONDS = 15.0
_DEFAULT_REGISTRATION_GRACE_SECONDS = 120.0
_MAX_TIMEOUT_SECONDS = 86400.0
_MAX_POLL_SECONDS = 300.0
_MAX_REGISTRATION_GRACE_SECONDS = 600.0
_GH_CALL_TIMEOUT_SECONDS = 30.0


class WaiterError(Exception):
    """Invalid waiter input or state path."""


class _APIError(Exception):
    def __init__(self, status: str, reason: str) -> None:
        super().__init__(reason)
        self.status = status
        self.reason = reason


class _MalformedResponse(Exception):
    """GitHub returned a successful response with an invalid shape."""


class _DeadlineExceeded(Exception):
    """The overall wait deadline expired during a GitHub CLI request."""


class _JournalError(Exception):
    """Durable observation state could not be written."""


def _utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )


def _finite_seconds(
    value: float | int,
    label: str,
    *,
    minimum: float,
    maximum: float,
    minimum_inclusive: bool = True,
) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise WaiterError(f"{label} must be a finite number of seconds")
    seconds = float(value)
    if not math.isfinite(seconds):
        raise WaiterError(f"{label} must be a finite number of seconds")
    lower_ok = seconds >= minimum if minimum_inclusive else seconds > minimum
    if not lower_ok or seconds > maximum:
        comparator = "at least" if minimum_inclusive else "greater than"
        raise WaiterError(
            f"{label} must be {comparator} {minimum:g} and no more than {maximum:g} seconds"
        )
    return seconds


def _validate_inputs(
    repository: str,
    pr_number: int,
    expected_head_sha: str,
    timeout_seconds: float,
    poll_interval_seconds: float,
    registration_grace_seconds: float,
) -> tuple[str, int, str, float, float, float]:
    if not isinstance(repository, str) or not _REPOSITORY_RE.fullmatch(repository):
        raise WaiterError("repository must be an owner/name value")
    owner, name = repository.split("/", 1)
    if owner in {".", ".."} or name in {".", ".."}:
        raise WaiterError("repository must be an owner/name value")
    if (
        not isinstance(pr_number, int)
        or isinstance(pr_number, bool)
        or pr_number <= 0
    ):
        raise WaiterError("PR number must be a positive integer")
    if not isinstance(expected_head_sha, str) or not _SHA_RE.fullmatch(expected_head_sha):
        raise WaiterError("expected head SHA must be a 40-64 character hexadecimal SHA")

    timeout = _finite_seconds(
        timeout_seconds,
        "timeout",
        minimum=0,
        maximum=_MAX_TIMEOUT_SECONDS,
        minimum_inclusive=False,
    )
    interval = _finite_seconds(
        poll_interval_seconds,
        "poll interval",
        minimum=1,
        maximum=_MAX_POLL_SECONDS,
    )
    grace = _finite_seconds(
        registration_grace_seconds,
        "registration grace period",
        minimum=0,
        maximum=_MAX_REGISTRATION_GRACE_SECONDS,
    )
    return (
        repository,
        pr_number,
        expected_head_sha.lower(),
        timeout,
        interval,
        grace,
    )


def _current_repository_root() -> Path | None:
    current = Path.cwd().resolve()
    for candidate in (current, *current.parents):
        if (candidate / ".git").exists():
            return candidate.resolve()
    return None


def _prepare_journal(state_dir: str | None) -> "_Journal | None":
    if state_dir is None:
        return None
    requested = Path(state_dir).expanduser()
    if requested.is_symlink():
        raise WaiterError("state directory must not be a symlink")
    path = requested.resolve()
    repo_root = _current_repository_root()
    if repo_root is not None:
        try:
            path.relative_to(repo_root)
        except ValueError:
            pass
        else:
            raise WaiterError("state directory must be outside the Git worktree")
    if path == path.parent:
        raise WaiterError("state directory must have a unique final path component")
    return _Journal(path)


def _fsync_directory(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


class _Journal:
    """Append durable, credential-free observations and an atomic final summary."""

    def __init__(self, path: Path) -> None:
        self.path = path
        try:
            path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            path.mkdir(mode=0o700)
            _fsync_directory(path.parent)
            fd = os.open(
                path / "observations.jsonl",
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
            )
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
            _fsync_directory(path)
        except FileExistsError as exc:
            raise WaiterError("state directory already exists; use a fresh unique path") from exc
        except OSError as exc:
            raise WaiterError(f"cannot create state directory ({type(exc).__name__})") from exc

    def record(self, event: dict[str, Any]) -> None:
        payload = (json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n").encode(
            "utf-8"
        )
        try:
            fd = os.open(self.path / "observations.jsonl", os.O_WRONLY | os.O_APPEND)
            try:
                offset = 0
                while offset < len(payload):
                    offset += os.write(fd, payload[offset:])
                os.fsync(fd)
            finally:
                os.close(fd)
        except OSError as exc:
            raise _JournalError(
                f"cannot append durable observation ({type(exc).__name__})"
            ) from exc

    def finish(self, result: dict[str, Any]) -> None:
        target = self.path / "summary.json"
        temporary: str | None = None
        try:
            fd, temporary = tempfile.mkstemp(
                prefix=".summary.", suffix=".tmp", dir=self.path
            )
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(result, stream, ensure_ascii=False, sort_keys=True)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, target)
            temporary = None
            _fsync_directory(self.path)
        except OSError as exc:
            raise _JournalError(
                f"cannot write durable summary ({type(exc).__name__})"
            ) from exc
        finally:
            if temporary is not None:
                try:
                    os.unlink(temporary)
                except FileNotFoundError:
                    pass

def _auth_failure(stderr: str) -> bool:
    lowered = stderr.lower()
    return any(
        marker in lowered
        for marker in (
            "not logged in",
            "authentication required",
            "requires authentication",
            "bad credentials",
            "http 401",
            "401 unauthorized",
        )
    )


def _gh_json(
    gh_path: str,
    route: str,
    *,
    paginate: bool,
    deadline: float,
    clock: Callable[[], float],
    cwd: Path,
) -> Any:
    remaining = deadline - clock()
    if remaining <= 0:
        raise _DeadlineExceeded
    argv = [gh_path, "api"]
    if paginate:
        argv.extend(["--paginate", "--slurp"])
    argv.append(route)
    environment = os.environ.copy()
    environment.update(
        {
            "GH_PROMPT_DISABLED": "1",
            "GH_NO_UPDATE_NOTIFIER": "1",
            "GIT_TERMINAL_PROMPT": "0",
            "NO_COLOR": "1",
        }
    )
    call_timeout = min(_GH_CALL_TIMEOUT_SECONDS, remaining)
    try:
        result = subprocess.run(
            argv,
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=environment,
            timeout=call_timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        if clock() >= deadline:
            raise _DeadlineExceeded from exc
        raise _APIError("gh_timeout", "gh api did not respond before its request timeout") from exc
    except OSError as exc:
        raise _APIError("gh_unavailable", f"cannot execute gh api ({type(exc).__name__})") from exc

    if result.returncode != 0:
        if _auth_failure(result.stderr or ""):
            raise _APIError(
                "unauthenticated",
                "gh is not authenticated or cannot access this repository",
            )
        raise _APIError(
            "gh_error",
            f"gh api request failed with exit code {result.returncode}",
        )
    try:
        return json.loads(result.stdout)
    except (json.JSONDecodeError, TypeError) as exc:
        raise _MalformedResponse("gh api returned invalid JSON") from exc


def _pull_head(payload: Any) -> str:
    if not isinstance(payload, dict):
        raise _MalformedResponse("pull request response must be a JSON object")
    head = payload.get("head")
    if not isinstance(head, dict):
        raise _MalformedResponse("pull request response has no head object")
    value = head.get("sha")
    if not isinstance(value, str) or not _SHA_RE.fullmatch(value):
        raise _MalformedResponse("pull request response has an invalid head SHA")
    return value.lower()


def _pages(payload: Any, label: str) -> list[dict[str, Any]]:
    if isinstance(payload, dict):
        return [payload]
    if isinstance(payload, list) and payload and all(isinstance(page, dict) for page in payload):
        return payload
    raise _MalformedResponse(f"{label} response must contain one or more JSON objects")


def _check_runs(payload: Any) -> list[dict[str, str | None]]:
    checks: list[dict[str, str | None]] = []
    for page in _pages(payload, "check-runs"):
        raw_runs = page.get("check_runs")
        if not isinstance(raw_runs, list):
            raise _MalformedResponse("check-runs response has no check_runs array")
        for raw in raw_runs:
            if not isinstance(raw, dict):
                raise _MalformedResponse("check-runs response contains a non-object entry")
            name = raw.get("name")
            status = raw.get("status")
            conclusion = raw.get("conclusion")
            if not isinstance(name, str) or not name.strip():
                raise _MalformedResponse("check run has no name")
            if not isinstance(status, str):
                raise _MalformedResponse(f"check run {name} has no status")
            if conclusion is not None and not isinstance(conclusion, str):
                raise _MalformedResponse(f"check run {name} has an invalid conclusion")
            checks.append(
                {
                    "name": name,
                    "source": "check_run",
                    "status": status,
                    "conclusion": conclusion,
                }
            )
    return checks


def _commit_statuses(payload: Any) -> tuple[list[dict[str, str | None]], list[str]]:
    checks: list[dict[str, str | None]] = []
    combined_states: list[str] = []
    for page in _pages(payload, "commit-status"):
        combined = page.get("state")
        if not isinstance(combined, str) or combined not in _STATUS_VALUES:
            raise _MalformedResponse("commit-status response has an invalid combined state")
        combined_states.append(combined)
        statuses = page.get("statuses")
        if not isinstance(statuses, list):
            raise _MalformedResponse("commit-status response has no statuses array")
        for raw in statuses:
            if not isinstance(raw, dict):
                raise _MalformedResponse("commit-status response contains a non-object entry")
            context = raw.get("context")
            state = raw.get("state")
            if not isinstance(context, str) or not context.strip():
                raise _MalformedResponse("commit status has no context")
            if not isinstance(state, str) or state not in _STATUS_VALUES:
                raise _MalformedResponse(f"commit status {context} has an invalid state")
            checks.append(
                {
                    "name": context,
                    "source": "commit_status",
                    "status": state,
                    "conclusion": None,
                }
            )
    return checks, combined_states


def _classify(
    checks: list[dict[str, str | None]],
    combined_states: list[str],
) -> tuple[str, list[dict[str, str | None]], str | None]:
    failed_combined = [
        state for state in combined_states if state in {"failure", "error"}
    ]
    if failed_combined:
        explicit_failures = [
            f"{check['name']} ({check['status']})"
            for check in checks
            if check.get("source") == "commit_status"
            and check.get("status") in {"failure", "error"}
        ]
        if not explicit_failures:
            checks = [
                *checks,
                {
                    "name": "combined commit status",
                    "source": "commit_status_summary",
                    "status": failed_combined[-1],
                    "conclusion": None,
                },
            ]
            explicit_failures = ["combined commit status"]
        return (
            "failed",
            checks,
            "checks did not succeed: " + ", ".join(explicit_failures[:20]),
        )
    if not checks:
        return "checks_not_registered", [], None

    pending: list[str] = []
    failed: list[str] = []
    for check in checks:
        source = check["source"]
        name = check["name"]
        status = check["status"]
        conclusion = check["conclusion"]
        if source == "check_run":
            if status in _CHECK_RUN_PENDING:
                pending.append(str(name))
            elif status == "completed":
                if conclusion is None:
                    raise _MalformedResponse(f"completed check run {name} has no conclusion")
                if conclusion in _TERMINAL_SUCCESS:
                    continue
                failed.append(f"{name} ({conclusion})")
            else:
                raise _MalformedResponse(f"check run {name} has unknown status {status}")
        elif source == "commit_status":
            if status == "pending":
                pending.append(str(name))
            elif status == "success":
                continue
            else:
                failed.append(f"{name} ({status})")
        else:
            raise _MalformedResponse("check result has an unknown source")

    if failed:
        return "failed", checks, "checks did not succeed: " + ", ".join(failed[:20])
    if pending:
        return "in_progress", checks, None
    return "success", checks, None

def _check_routes(repository: str, sha: str) -> tuple[str, str]:
    prefix = f"repos/{repository}/commits/{sha}"
    return (
        f"{prefix}/check-runs?filter=latest&per_page=100",
        f"{prefix}/status?per_page=100",
    )


def wait_for_checks(
    *,
    repository: str,
    pr_number: int,
    expected_head_sha: str,
    timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
    poll_interval_seconds: float = _DEFAULT_POLL_SECONDS,
    registration_grace_seconds: float = _DEFAULT_REGISTRATION_GRACE_SECONDS,
    state_dir: str | None = None,
    gh_bin: str = "gh",
    clock: Callable[[], float] | None = None,
    sleeper: Callable[[float], None] | None = None,
) -> dict[str, Any]:
    (
        repository,
        pr_number,
        expected_sha,
        timeout,
        interval,
        grace,
    ) = _validate_inputs(
        repository,
        pr_number,
        expected_head_sha,
        timeout_seconds,
        poll_interval_seconds,
        registration_grace_seconds,
    )
    now = time.monotonic if clock is None else clock
    sleep = time.sleep if sleeper is None else sleeper
    journal = _prepare_journal(state_dir)
    started_at = _utc_now()
    started = now()
    deadline = started + timeout
    current_sha: str | None = None
    observed_checks: list[dict[str, str | None]] = []
    poll_count = 0

    def finish(
        status: str,
        *,
        failure_reason: str | None = None,
    ) -> dict[str, Any]:
        elapsed = max(0.0, now() - started)
        result: dict[str, Any] = {
            "repository": repository,
            "pr_number": pr_number,
            "expected_head_sha": expected_sha,
            "current_head_sha": current_sha,
            "observed_checks": observed_checks,
            "poll_count": poll_count,
            "started_at": started_at,
            "finished_at": _utc_now(),
            "elapsed_seconds": round(elapsed, 3),
            "status": status,
            "failure_reason": failure_reason,
        }
        if journal is not None:
            result["state_dir"] = str(journal.path)
            try:
                journal.finish(result)
            except _JournalError as exc:
                result["status"] = "state_error"
                result["failure_reason"] = str(exc)
        return result

    gh_path = shutil.which(gh_bin)
    if not gh_path:
        return finish("gh_unavailable", failure_reason="gh executable was not found on PATH")

    pull_route = f"repos/{repository}/pulls/{pr_number}"
    check_route, status_route = _check_routes(repository, expected_sha)
    cwd = Path.cwd()
    while True:
        if now() >= deadline:
            return finish("timed_out", failure_reason="timed out waiting for checks")
        poll_count += 1
        try:
            before_sha = _pull_head(
                _gh_json(
                    gh_path,
                    pull_route,
                    paginate=False,
                    deadline=deadline,
                    clock=now,
                    cwd=cwd,
                )
            )
            current_sha = before_sha
            if before_sha != expected_sha:
                return finish(
                    "head_changed",
                    failure_reason="pull request head no longer matches the expected SHA",
                )

            runs = _check_runs(
                _gh_json(
                    gh_path,
                    check_route,
                    paginate=True,
                    deadline=deadline,
                    clock=now,
                    cwd=cwd,
                )
            )
            statuses, combined = _commit_statuses(
                _gh_json(
                    gh_path,
                    status_route,
                    paginate=True,
                    deadline=deadline,
                    clock=now,
                    cwd=cwd,
                )
            )
            after_sha = _pull_head(
                _gh_json(
                    gh_path,
                    pull_route,
                    paginate=False,
                    deadline=deadline,
                    clock=now,
                    cwd=cwd,
                )
            )
            current_sha = after_sha
            if after_sha != expected_sha:
                return finish(
                    "head_changed",
                    failure_reason="pull request head changed while checks were being observed",
                )
            observed_checks = runs + statuses
            state, observed_checks, failure_reason = _classify(
                observed_checks, combined
            )
            event = {
                "repository": repository,
                "pr_number": pr_number,
                "expected_head_sha": expected_sha,
                "current_head_sha": current_sha,
                "poll": poll_count,
                "observed_at": _utc_now(),
                "elapsed_seconds": round(max(0.0, now() - started), 3),
                "status": state,
                "observed_checks": observed_checks,
            }
            if journal is not None:
                journal.record(event)
        except _DeadlineExceeded:
            return finish("timed_out", failure_reason="timed out waiting for checks")
        except _APIError as exc:
            return finish(exc.status, failure_reason=exc.reason)
        except _MalformedResponse as exc:
            return finish("malformed_response", failure_reason=str(exc))

        if state == "success":
            return finish("success")
        if state == "failed":
            return finish("failed", failure_reason=failure_reason)
        elapsed = max(0.0, now() - started)
        if state == "checks_not_registered" and elapsed >= grace:
            return finish(
                "checks_not_registered",
                failure_reason=(
                    f"no checks registered within the {grace:g}-second registration grace period"
                ),
            )
        remaining = deadline - now()
        if remaining <= 0:
            return finish("timed_out", failure_reason="timed out waiting for checks")
        sleep(min(interval, remaining))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="operation", required=True)
    wait = commands.add_parser("wait", help="wait for checks on one exact PR head")
    wait.add_argument("--repo", required=True, help="GitHub repository in owner/name form")
    wait.add_argument("--pr", required=True, type=int, help="pull-request number")
    wait.add_argument("--head-sha", required=True, help="expected PR head SHA")
    wait.add_argument(
        "--timeout-seconds",
        type=float,
        default=_DEFAULT_TIMEOUT_SECONDS,
        help="overall wait limit (default: 1800 seconds)",
    )
    wait.add_argument(
        "--poll-interval-seconds",
        type=float,
        default=_DEFAULT_POLL_SECONDS,
        help="poll interval, bounded to 1-300 seconds (default: 15)",
    )
    wait.add_argument(
        "--registration-grace-seconds",
        type=float,
        default=_DEFAULT_REGISTRATION_GRACE_SECONDS,
        help="bounded wait for the first visible check (default: 120 seconds)",
    )
    wait.add_argument(
        "--state-dir",
        help="fresh external directory for durable observations and final summary",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    try:
        result = wait_for_checks(
            repository=args.repo,
            pr_number=args.pr,
            expected_head_sha=args.head_sha,
            timeout_seconds=args.timeout_seconds,
            poll_interval_seconds=args.poll_interval_seconds,
            registration_grace_seconds=args.registration_grace_seconds,
            state_dir=args.state_dir,
        )
    except WaiterError as exc:
        result = {
            "status": "invalid_input",
            "failure_reason": str(exc),
        }
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result.get("status") == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())
