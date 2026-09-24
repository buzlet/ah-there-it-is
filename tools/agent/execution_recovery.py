#!/usr/bin/env python3
"""Materialize exact task prompts and recover one Codex lifecycle per branch."""

from __future__ import annotations

import argparse
import datetime as dt
import errno
import fcntl
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any

try:  # Support both ``python -m`` and direct script invocation.
    from . import codex_session, lifecycle_checkpoints
except ImportError:  # pragma: no cover - exercised by the documented CLI path.
    import codex_session  # type: ignore[no-redef]
    import lifecycle_checkpoints  # type: ignore[no-redef]


_SHA_RE = re.compile(r"^[0-9a-f]{40,64}$")
_TASK_RE = re.compile(r"^[0-9]{4}$")
_VALID_PR_STATES = {"not_created", "open", "merged", "closed", "unknown"}
_VALID_CI_STATES = {
    "not_started",
    "queued",
    "in_progress",
    "success",
    "failed",
    "timed_out",
    "head_changed",
    "unknown",
}
_RECOVERY_STATE_KEYS = {
    "branch",
    "branch_head",
    "main_head",
    "pr_number",
    "pr_head_sha",
    "pr_state",
    "ci_state",
    "lifecycle_phase",
}


class RecoveryError(Exception):
    """An expected prompt or recovery state error."""


def _utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )


def _git_raw(repo: Path, *args: str, timeout: float = 15.0) -> subprocess.CompletedProcess[bytes]:
    environment = os.environ.copy()
    environment["GIT_OPTIONAL_LOCKS"] = "0"
    environment["GIT_TERMINAL_PROMPT"] = "0"
    try:
        return subprocess.run(
            ["git", "-C", str(repo), *args],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=timeout,
            env=environment,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RecoveryError(f"local git command failed: {args[0] if args else 'git'}") from exc


def _git(repo: Path, *args: str, timeout: float = 15.0) -> str:
    result = _git_raw(repo, *args, timeout=timeout)
    if result.returncode:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise RecoveryError(f"git {args[0]} failed: {detail[:300]}")
    return result.stdout.decode("utf-8", errors="strict").strip()


def _repo_and_state(repo_path: str, state_dir: str) -> tuple[Path, Path]:
    repo = Path(repo_path).expanduser().resolve()
    state = Path(state_dir).expanduser().resolve()
    if not repo.is_dir():
        raise RecoveryError("repository path must be an existing directory")
    root = Path(_git(repo, "rev-parse", "--show-toplevel")).resolve()
    if root != repo:
        raise RecoveryError("repo must be the root of the selected Git worktree")
    try:
        state.relative_to(repo)
    except ValueError:
        pass
    else:
        raise RecoveryError("helper state must be outside the repository worktree")
    state.mkdir(parents=True, exist_ok=True, mode=0o700)
    if state.is_symlink():
        raise RecoveryError("helper state directory must not be a symlink")
    return repo, state


def _safe_relative_path(value: str, label: str) -> str:
    if not value or "\\" in value:
        raise RecoveryError(f"{label} must be a repository-relative path")
    path = PurePosixPath(value)
    if path.is_absolute() or path.as_posix() == "." or any(
        part in {"", ".", ".."} for part in path.parts
    ):
        raise RecoveryError(f"{label} must be a safe repository-relative path")
    return path.as_posix()


def _is_commit(repo: Path, sha: str) -> bool:
    return bool(_SHA_RE.fullmatch(sha)) and _git_raw(
        repo, "cat-file", "-e", f"{sha}^{{commit}}"
    ).returncode == 0


def _git_common_dir(repo: Path) -> Path:
    raw = Path(_git(repo, "rev-parse", "--git-common-dir"))
    return (raw if raw.is_absolute() else repo / raw).resolve()


def _read_blob(repo: Path, commit: str, path: str) -> bytes:
    result = _git_raw(repo, "show", f"{commit}:{path}")
    if result.returncode:
        raise RecoveryError(f"cannot read {path} at the supplied control SHA")
    return result.stdout


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise RecoveryError("prompt file cannot be read") from exc
    return digest.hexdigest()


def _write_once(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.is_symlink():
        raise RecoveryError("output file must not be a symlink")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags, 0o600)
    except FileExistsError as exc:
        raise RecoveryError("output already exists; materialized prompts are immutable") from exc
    try:
        view = memoryview(data)
        while view:
            written = os.write(fd, view)
            view = view[written:]
        os.fsync(fd)
    except OSError:
        os.close(fd)
        path.unlink(missing_ok=True)
        raise
    else:
        os.close(fd)
    directory_fd = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def _read_json(path: Path, label: str) -> dict[str, Any]:
    if path.is_symlink():
        raise RecoveryError(f"{label} must not be a symlink")
    try:
        with path.open("r", encoding="utf-8") as stream:
            value = json.load(stream)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RecoveryError(f"cannot read valid {label}") from exc
    if not isinstance(value, dict):
        raise RecoveryError(f"{label} must contain a JSON object")
    return value


def _prompt_paths(output_path: str, repo: Path) -> tuple[Path, Path]:
    output = Path(output_path).expanduser()
    parent = output.parent.resolve()
    prompt = parent / output.name
    metadata = parent / f"{output.name}.metadata.json"
    for path in (prompt, metadata):
        try:
            path.relative_to(repo)
        except ValueError:
            pass
        else:
            raise RecoveryError("prompt and metadata must be outside the repository worktree")
    return prompt, metadata


def _continuation_state(path: str, *, branch: str) -> dict[str, Any]:
    value = _read_json(Path(path).expanduser().resolve(), "continuation state")
    if set(value) != _RECOVERY_STATE_KEYS:
        raise RecoveryError("continuation state has missing or unexpected fields")
    if value.get("branch") != branch:
        raise RecoveryError("continuation state branch does not match the assignment")
    for field in ("branch_head", "main_head"):
        if not isinstance(value.get(field), str) or not _SHA_RE.fullmatch(value[field]):
            raise RecoveryError(f"continuation state {field} must be a full commit SHA")
    pr_number = value.get("pr_number")
    if pr_number is not None and (not isinstance(pr_number, int) or pr_number <= 0):
        raise RecoveryError("continuation state pr_number must be a positive integer or null")
    pr_head = value.get("pr_head_sha")
    if pr_head is not None and (not isinstance(pr_head, str) or not _SHA_RE.fullmatch(pr_head)):
        raise RecoveryError("continuation state pr_head_sha must be a full commit SHA or null")
    if value.get("pr_state") not in _VALID_PR_STATES:
        raise RecoveryError("continuation state has an unsupported pr_state")
    if pr_number is None and (pr_head is not None or value["pr_state"] != "not_created"):
        raise RecoveryError("continuation state PR number/head/state are inconsistent")
    if pr_number is not None and pr_head is None:
        raise RecoveryError("an existing PR requires its exact current head SHA")
    if value.get("ci_state") not in _VALID_CI_STATES:
        raise RecoveryError("continuation state has an unsupported ci_state")
    if pr_number is None and value["ci_state"] != "not_started":
        raise RecoveryError("CI state must be not_started when no PR exists")
    if value.get("lifecycle_phase") not in lifecycle_checkpoints.PHASES:
        raise RecoveryError("continuation state has an unsupported lifecycle_phase")
    return value


def materialize_prompt(
    *,
    repo_path: str,
    control_sha: str,
    manifest_path: str,
    task_id: str,
    task_order: list[str],
    start_main_sha: str,
    output_path: str,
    host_profile: str = "u24-bash",
    execution_channel: str = "ssh-codex",
    continuation_from: str | None = None,
    continuation_state_file: str | None = None,
) -> dict[str, Any]:
    if os.name != "posix":
        raise RecoveryError("execution recovery helper supports POSIX hosts only")
    repo = Path(repo_path).expanduser().resolve()
    if not repo.is_dir() or Path(_git(repo, "rev-parse", "--show-toplevel")).resolve() != repo:
        raise RecoveryError("repo must be the root of an existing Git worktree")
    if host_profile != "u24-bash" or execution_channel != "ssh-codex":
        raise RecoveryError("prompt materialization supports only u24-bash + ssh-codex")
    if not _SHA_RE.fullmatch(control_sha) or not _is_commit(repo, control_sha):
        raise RecoveryError("control SHA must identify an existing immutable commit")
    if not _is_commit(repo, start_main_sha):
        raise RecoveryError("start-main SHA must identify an existing commit")
    if not _TASK_RE.fullmatch(task_id):
        raise RecoveryError("task ID must be four digits")
    manifest_path = _safe_relative_path(manifest_path, "manifest path")
    manifest_bytes = _read_blob(repo, control_sha, manifest_path)
    try:
        manifest = lifecycle_checkpoints.parse_manifest(manifest_bytes.decode("utf-8"))
    except (UnicodeError, lifecycle_checkpoints.LifecycleError) as exc:
        raise RecoveryError("manifest at the control SHA is invalid") from exc
    actual_order = [task["id"] for task in manifest["tasks"]]
    if actual_order != task_order:
        raise RecoveryError("supplied task order does not match the immutable manifest")
    selected = next((task for task in manifest["tasks"] if task["id"] == task_id), None)
    if selected is None:
        raise RecoveryError("selected task does not exist in the immutable manifest")
    task_source = _safe_relative_path(selected["spec_source"], "task specification source")
    assignment = _read_blob(repo, control_sha, task_source)
    branch = selected["branch"]

    continuation: dict[str, Any] | None = None
    if continuation_from is not None:
        codex_session._validate_run_id(continuation_from)
        if not continuation_state_file:
            raise RecoveryError("continuation requires a durable continuation-state file")
        continuation_path = Path(continuation_state_file).expanduser().resolve()
        try:
            continuation_path.relative_to(repo)
        except ValueError:
            pass
        else:
            raise RecoveryError("continuation state must be outside the repository worktree")
        continuation = _continuation_state(continuation_state_file, branch=branch)
    elif continuation_state_file is not None:
        raise RecoveryError("continuation state requires --continuation-from")

    header = [
        "You are Codex CLI implementing one exact issued assignment.",
        f"Repository: {repo}",
        "Protocol: agent-tasks/common/v7.md",
        f"host_profile: {host_profile}",
        f"execution_channel: {execution_channel}",
        f"Immutable control SHA: {control_sha}",
        f"Manifest: {manifest_path}",
        f"Task: {task_id}",
        f"Task branch: {branch}",
        f"Task order: {','.join(actual_order)}",
        f"Start-main SHA: {start_main_sha}",
        "Read protocol and assignment bytes from the immutable control SHA.",
        "Preserve the assignment scope, lifecycle, verification, and stop rules.",
        "Do not change product semantics or reinterpret the issued assignment.",
        "Never start a second implementation process on the same task branch.",
    ]
    if continuation is not None:
        header.extend(
            [
                f"Continuation from run: {continuation_from}",
                "Continue the existing lifecycle from this recorded durable state.",
                "Do not recreate or replace the seed, rebase, or recreate the PR.",
                "Preserve existing review and PR; rerun required verification after corrections.",
                "Do not reinterpret the assignment scope.",
                "Durable branch, main, PR, CI, and lifecycle state:",
                json.dumps(continuation, sort_keys=True, separators=(",", ":")),
            ]
        )
    header.extend(
        [
            "Return one compact protocol report after final durable Git/PR/merge verification.",
            "",
            "----- BEGIN EXACT ASSIGNMENT BYTES -----",
            "",
        ]
    )
    prompt_bytes = "\n".join(header).encode("utf-8") + assignment
    if not prompt_bytes.endswith(b"\n"):
        prompt_bytes += b"\n"
    prompt_bytes += b"\n----- END EXACT ASSIGNMENT BYTES -----\n"
    output, metadata_path = _prompt_paths(output_path, repo)
    metadata = {
        "schema_version": 1,
        "repo_path": str(repo),
        "control_sha": control_sha,
        "manifest_path": manifest_path,
        "task_id": task_id,
        "task_source": task_source,
        "branch": branch,
        "start_main_sha": start_main_sha,
        "task_order": actual_order,
        "host_profile": host_profile,
        "execution_channel": execution_channel,
        "continuation_from": continuation_from,
        "continuation_state": continuation,
        "spec_sha256": _sha256_bytes(assignment),
        "prompt_sha256": _sha256_bytes(prompt_bytes),
        "materialized_at": _utc_now(),
    }
    _write_once(output, prompt_bytes)
    try:
        _write_once(
            metadata_path,
            (json.dumps(metadata, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8"),
        )
    except Exception:
        output.unlink(missing_ok=True)
        raise
    return {
        "status": "materialized",
        "prompt_path": str(output),
        "metadata_path": str(metadata_path),
        "prompt_sha256": metadata["prompt_sha256"],
        "spec_sha256": metadata["spec_sha256"],
        "control_sha": control_sha,
        "task_id": task_id,
        "branch": branch,
        "continuation_from": continuation_from,
    }


def _ref_sha(repo: Path, ref: str) -> str | None:
    result = _git_raw(repo, "rev-parse", "--verify", f"{ref}^{{commit}}")
    if result.returncode:
        return None
    return result.stdout.decode("ascii", errors="replace").strip()


def _is_ancestor(repo: Path, ancestor: str, descendant: str) -> bool:
    result = _git_raw(repo, "merge-base", "--is-ancestor", ancestor, descendant)
    if result.returncode == 0:
        return True
    if result.returncode == 1:
        return False
    raise RecoveryError("git could not compare durable commit ancestry")


def reconcile_git(
    *,
    repo_path: str,
    branch: str,
    base_sha: str,
    main_ref: str = "origin/main",
) -> dict[str, Any]:
    repo = Path(repo_path).expanduser().resolve()
    if not repo.is_dir() or Path(_git(repo, "rev-parse", "--show-toplevel")).resolve() != repo:
        raise RecoveryError("repo must be the root of an existing Git worktree")
    if not _SHA_RE.fullmatch(base_sha) or not _is_commit(repo, base_sha):
        raise RecoveryError("base SHA must identify an existing commit")
    if not branch or branch.startswith("-"):
        raise RecoveryError("branch must be a valid local branch name")
    branch_ref = f"refs/heads/{branch}"
    if _git_raw(repo, "check-ref-format", branch_ref).returncode:
        raise RecoveryError("branch must be a valid local branch name")
    normalized_main_ref = main_ref if main_ref.startswith("refs/") else f"refs/remotes/{main_ref}"
    if _git_raw(repo, "check-ref-format", normalized_main_ref).returncode:
        raise RecoveryError("main ref is invalid")
    branch_head = _ref_sha(repo, branch_ref)
    main_head = _ref_sha(repo, normalized_main_ref)
    if branch_head is None:
        status = "branch_missing"
    elif main_head is None:
        status = "main_ref_missing"
    elif not _is_ancestor(repo, base_sha, branch_head):
        status = "branch_diverged"
    elif branch_head == base_sha and main_head == base_sha:
        status = "seed_missing"
    elif branch_head == base_sha and _is_ancestor(repo, base_sha, main_head):
        status = "external_main_advance"
    elif _is_ancestor(repo, branch_head, main_head):
        commits_after_base = int(_git(repo, "rev-list", "--count", f"{base_sha}..{branch_head}"))
        status = "seed_only_merged" if commits_after_base <= 1 else "merged"
    elif main_head == base_sha:
        status = "in_progress"
    elif _is_ancestor(repo, base_sha, main_head):
        status = "external_main_advance"
    else:
        status = "main_diverged"
    return {
        "status": status,
        "branch": branch,
        "branch_head": branch_head,
        "base_sha": base_sha,
        "main_ref": normalized_main_ref,
        "main_head": main_head,
    }


def _state_paths(state: Path, repo: Path, branch: str) -> tuple[Path, Path, Path]:
    branch_ref = f"refs/heads/{branch}"
    if _git_raw(repo, "check-ref-format", branch_ref).returncode:
        raise RecoveryError("branch must be a valid local branch name")
    lock_dir = state / "branch-locks"
    lock_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    if lock_dir.is_symlink():
        raise RecoveryError("branch lock directory must not be a symlink")
    common_dir = _git_common_dir(repo)
    digest = hashlib.sha256(f"{common_dir}\0{branch}".encode("utf-8")).hexdigest()
    lock_path = lock_dir / f"{digest}.lock"
    owner_path = lock_dir / f"{digest}.owner.json"
    if lock_path.is_symlink() or owner_path.is_symlink():
        raise RecoveryError("branch lock files must not be symlinks")
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
    try:
        lock_fd = os.open(lock_path, flags, 0o600)
    except OSError as exc:
        raise RecoveryError("cannot open branch recovery lock") from exc
    os.fchmod(lock_fd, 0o600)
    return lock_path, owner_path, lock_fd


def _read_owner(path: Path, *, repo: Path, branch: str) -> dict[str, Any] | None:
    if not path.exists() and not path.is_symlink():
        return None
    value = _read_json(path, "branch owner record")
    if (
        value.get("schema_version") != 1
        or value.get("repo_path") != str(repo)
        or value.get("git_common_dir") != str(_git_common_dir(repo))
        or value.get("branch") != branch
        or not isinstance(value.get("run_id"), str)
    ):
        raise RecoveryError("branch owner record does not match this repository and branch")
    codex_session._validate_run_id(value["run_id"])
    return value


def _lock(lock_fd: int) -> tuple[bool, str | None]:
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return False, None
    except OSError as exc:
        if exc.errno in {errno.EACCES, errno.EAGAIN}:
            return False, None
        raise RecoveryError("cannot inspect branch recovery lock") from exc
    return True, None


def _prompt_metadata(prompt_file: str, repo: Path) -> tuple[Path, dict[str, Any]]:
    prompt = Path(prompt_file).expanduser().resolve()
    try:
        prompt.relative_to(repo)
    except ValueError:
        pass
    else:
        raise RecoveryError("prompt file must be outside the repository worktree")
    metadata_path = prompt.with_name(f"{prompt.name}.metadata.json")
    metadata = _read_json(metadata_path, "materialized prompt metadata")
    if metadata.get("schema_version") != 1 or metadata.get("repo_path") != str(repo):
        raise RecoveryError("prompt metadata belongs to another repository or schema")
    if (
        not isinstance(metadata.get("control_sha"), str)
        or not _SHA_RE.fullmatch(metadata["control_sha"])
        or not _is_commit(repo, metadata["control_sha"])
        or not isinstance(metadata.get("start_main_sha"), str)
        or not _SHA_RE.fullmatch(metadata["start_main_sha"])
        or not _is_commit(repo, metadata["start_main_sha"])
        or not isinstance(metadata.get("branch"), str)
        or not isinstance(metadata.get("task_id"), str)
        or not _TASK_RE.fullmatch(metadata["task_id"])
    ):
        raise RecoveryError("prompt metadata has invalid control, task, or branch identity")
    if metadata.get("prompt_sha256") != _sha256_file(prompt):
        raise RecoveryError("prompt bytes changed after materialization")
    return prompt, metadata


def _matching_active_sessions(
    state: Path, repo: Path, *, exclude_run_id: str | None
) -> list[dict[str, Any]]:
    run_root = state / "codex-runs"
    if not run_root.is_dir():
        return []
    active: list[dict[str, Any]] = []
    current_common_dir = _git_common_dir(repo)
    for run_dir in sorted(run_root.iterdir()):
        if run_dir.name == exclude_run_id or not run_dir.is_dir() or run_dir.is_symlink():
            continue
        try:
            metadata = _read_json(run_dir / "metadata.json", "Codex run metadata")
        except RecoveryError:
            continue
        session_repo = metadata.get("repo_path")
        if not isinstance(session_repo, str) or not isinstance(metadata.get("run_id"), str):
            continue
        try:
            session_common_dir = _git_common_dir(Path(session_repo).resolve())
        except (RecoveryError, OSError):
            continue
        if session_common_dir != current_common_dir:
            continue
        status = codex_session.status_run(run_id=metadata["run_id"], state_dir=str(run_root))
        if status.get("status") in {"running", "invalid"}:
            active.append({"run_id": metadata["run_id"], "status": status.get("status")})
    return active


def start_run(
    *,
    repo_path: str,
    branch: str,
    run_id: str,
    prompt_file: str,
    state_dir: str,
    control_sha: str,
    task_id: str,
    continuation_from: str | None = None,
    codex_bin: str = "codex",
    main_ref: str = "origin/main",
) -> dict[str, Any]:
    if os.name != "posix":
        raise RecoveryError("execution recovery helper supports POSIX hosts only")
    safe_run_id = codex_session._validate_run_id(run_id)
    if not _SHA_RE.fullmatch(control_sha) or not _TASK_RE.fullmatch(task_id):
        raise RecoveryError("control SHA or task ID is invalid")
    repo, state = _repo_and_state(repo_path, state_dir)
    current_branch = _git(repo, "symbolic-ref", "--quiet", "--short", "HEAD")
    if current_branch != branch:
        raise RecoveryError("checked-out branch does not match requested assignment branch")
    prompt, prompt_meta = _prompt_metadata(prompt_file, repo)
    if (
        prompt_meta.get("branch") != branch
        or prompt_meta.get("control_sha") != control_sha
        or prompt_meta.get("task_id") != task_id
        or prompt_meta.get("continuation_from") != continuation_from
    ):
        raise RecoveryError("materialized prompt identity does not match the requested run")

    git_state = reconcile_git(
        repo_path=str(repo),
        branch=branch,
        base_sha=prompt_meta["start_main_sha"],
        main_ref=main_ref,
    )
    continuation_state = prompt_meta.get("continuation_state")
    if continuation_state is not None and (
        continuation_state.get("branch_head") != git_state.get("branch_head")
        or continuation_state.get("main_head") != git_state.get("main_head")
    ):
        return {
            "status": "blocked",
            "reason": "continuation prompt Git state no longer matches local durable refs",
            "git": git_state,
            "run_id": safe_run_id,
        }
    if git_state["status"] == "merged":
        return {"status": "already_merged", "git": git_state, "run_id": safe_run_id}
    if git_state["status"] != "in_progress":
        return {
            "status": "blocked",
            "reason": f"durable Git state is {git_state['status']}",
            "git": git_state,
            "run_id": safe_run_id,
        }

    _lock_path, owner_path, lock_fd = _state_paths(state, repo, branch)
    acquired, _ = _lock(lock_fd)
    if not acquired:
        try:
            owner = _read_owner(owner_path, repo=repo, branch=branch)
        except RecoveryError as exc:
            os.close(lock_fd)
            return {"status": "blocked", "reason": str(exc), "run_id": safe_run_id}
        os.close(lock_fd)
        if owner is None:
            return {
                "status": "blocked",
                "reason": "branch lock is held but has no readable owner record",
                "run_id": safe_run_id,
            }
        previous = codex_session.status_run(
            run_id=owner["run_id"], state_dir=str(state / "codex-runs")
        )
        return {
            "status": "already_running",
            "run_id": owner["run_id"],
            "process": previous,
            "branch": branch,
            "recommendation": "keep_observing_existing_lifecycle",
        }

    try:
        try:
            owner = _read_owner(owner_path, repo=repo, branch=branch)
        except RecoveryError as exc:
            return {"status": "blocked", "reason": str(exc), "run_id": safe_run_id}

        previous_status: dict[str, Any] | None = None
        if owner is None:
            if continuation_from is not None:
                return {
                    "status": "blocked",
                    "reason": "continuation was requested but no prior helper run exists",
                    "run_id": safe_run_id,
                }
        else:
            previous_status = codex_session.status_run(
                run_id=owner["run_id"], state_dir=str(state / "codex-runs")
            )
            prior_state = previous_status.get("status")
            if prior_state == "running":
                return {
                    "status": "already_running",
                    "run_id": owner["run_id"],
                    "process": previous_status,
                    "recommendation": "keep_observing_existing_lifecycle",
                }
            if prior_state not in {"completed", "failed", "terminated", "stale"}:
                return {
                    "status": "blocked",
                    "reason": f"previous run state {prior_state} is not safe to continue",
                    "run_id": safe_run_id,
                    "previous_run_id": owner["run_id"],
                    "process": previous_status,
                }
            if continuation_from != owner["run_id"]:
                return {
                    "status": "continuation_required",
                    "reason": "new run requires an explicit continuation from the last run",
                    "run_id": safe_run_id,
                    "previous_run_id": owner["run_id"],
                    "previous_status": prior_state,
                }
            if owner.get("control_sha") != control_sha or owner.get("task_id") != task_id:
                return {
                    "status": "blocked",
                    "reason": "continuation changed immutable control or assignment identity",
                    "run_id": safe_run_id,
                    "previous_run_id": owner["run_id"],
                }
            if owner.get("start_main_sha") != prompt_meta.get("start_main_sha"):
                return {
                    "status": "blocked",
                    "reason": "continuation changed the immutable start-main SHA",
                    "run_id": safe_run_id,
                    "previous_run_id": owner["run_id"],
                }

        active = _matching_active_sessions(
            state, repo, exclude_run_id=owner["run_id"] if owner else None
        )
        if active:
            return {
                "status": "blocked",
                "reason": "another Codex session for this repository is active or unverifiable",
                "active_sessions": active,
                "run_id": safe_run_id,
            }
        if previous_status is not None and _git(repo, "rev-parse", "HEAD") != git_state["branch_head"]:
            return {
                "status": "blocked",
                "reason": "checked-out branch HEAD changed during recovery inspection",
                "run_id": safe_run_id,
            }
        if _git(repo, "rev-parse", "HEAD") != git_state["branch_head"]:
            return {
                "status": "blocked",
                "reason": "checked-out branch HEAD does not match its durable branch ref",
                "run_id": safe_run_id,
            }

        new_owner = {
            "schema_version": 1,
            "repo_path": str(repo),
            "git_common_dir": str(_git_common_dir(repo)),
            "branch": branch,
            "run_id": safe_run_id,
            "control_sha": control_sha,
            "task_id": task_id,
            "start_main_sha": prompt_meta["start_main_sha"],
            "branch_head_at_start": git_state["branch_head"],
            "prompt_sha256": prompt_meta["prompt_sha256"],
            "continuation_from": continuation_from,
            "started_at": _utc_now(),
        }
        _atomic_json(owner_path, new_owner)
        try:
            process = codex_session.start_run(
                run_id=safe_run_id,
                repo_path=str(repo),
                prompt_file=str(prompt),
                state_dir=str(state / "codex-runs"),
                codex_bin=codex_bin,
                _hold_fd=lock_fd,
            )
        except codex_session.SessionError as exc:
            new_owner["launch_error"] = " ".join(str(exc).split())[:300]
            _atomic_json(owner_path, new_owner)
            return {"status": "failed", "reason": new_owner["launch_error"], "run_id": safe_run_id}
        return {
            "status": process.get("status", "unknown"),
            "run_id": safe_run_id,
            "branch": branch,
            "process": process,
            "git": git_state,
            "continuation_from": continuation_from,
        }
    finally:
        os.close(lock_fd)


def status_run(*, repo_path: str, branch: str, state_dir: str, main_ref: str = "origin/main") -> dict[str, Any]:
    repo, state = _repo_and_state(repo_path, state_dir)
    _lock_path, owner_path, lock_fd = _state_paths(state, repo, branch)
    acquired, _ = _lock(lock_fd)
    lock_held = not acquired
    try:
        owner = _read_owner(owner_path, repo=repo, branch=branch)
    finally:
        os.close(lock_fd)
    if owner is None:
        return {
            "status": "blocked" if lock_held else "not_started",
            "branch": branch,
            "lock_held": lock_held,
            "recommendation": "inspect_lock_owner_before_any_launch" if lock_held else None,
        }
    process = codex_session.status_run(
        run_id=owner["run_id"], state_dir=str(state / "codex-runs")
    )
    base_sha = owner.get("start_main_sha")
    if not isinstance(base_sha, str) or not _SHA_RE.fullmatch(base_sha):
        git_state: dict[str, Any] = {
            "status": "unavailable",
            "reason": "owner record has no valid start-main SHA",
        }
    else:
        git_state = reconcile_git(
            repo_path=str(repo),
            branch=branch,
            base_sha=base_sha,
            main_ref=main_ref,
        )
    process_state = process.get("status")
    if git_state.get("status") == "merged" and process_state != "running" and not lock_held:
        overall = "merged"
        recommendation = "verify_PR_CI_clean_main_and_seed_ancestry"
    elif lock_held or process_state == "running":
        overall = "running"
        recommendation = "keep_observing_existing_lifecycle"
    elif process_state == "invalid":
        overall = "blocked"
        recommendation = "stop_and_report_unverifiable_process_state"
    elif process_state == "stale":
        overall = "stale"
        recommendation = "inspect_trace_and_durable_Git_before_explicit_continuation"
    else:
        overall = process_state or "unknown"
        recommendation = "inspect_trace_PR_CI_and_Git_before_continuation"
    if git_state.get("status") in {
        "external_main_advance",
        "main_diverged",
        "branch_diverged",
        "seed_only_merged",
    }:
        overall = "blocked"
        recommendation = "stop_for_unexpected_durable_Git_advance"
    return {
        "status": overall,
        "branch": branch,
        "run_id": owner["run_id"],
        "lock_held": lock_held,
        "process": process,
        "git": git_state,
        "recommendation": recommendation,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="operation", required=True)

    materialize = commands.add_parser("materialize", help="write immutable prompt bytes outside the worktree")
    materialize.add_argument("--repo", required=True)
    materialize.add_argument("--control-sha", required=True)
    materialize.add_argument("--manifest", required=True)
    materialize.add_argument("--task", required=True)
    materialize.add_argument("--task-order", required=True)
    materialize.add_argument("--start-main-sha", required=True)
    materialize.add_argument("--output", required=True)
    materialize.add_argument("--host-profile", choices=["u24-bash"], default="u24-bash")
    materialize.add_argument("--execution-channel", choices=["ssh-codex"], default="ssh-codex")
    materialize.add_argument("--continuation-from")
    materialize.add_argument("--continuation-state-file")

    start = commands.add_parser("start", help="start or explicitly continue one branch-locked Codex lifecycle")
    start.add_argument("--repo", required=True)
    start.add_argument("--branch", required=True)
    start.add_argument("--run-id", required=True)
    start.add_argument("--prompt-file", required=True)
    start.add_argument("--state-dir", required=True)
    start.add_argument("--control-sha", required=True)
    start.add_argument("--task", required=True)
    start.add_argument("--continuation-from")
    start.add_argument("--codex-bin", default="codex")
    start.add_argument("--main-ref", default="origin/main")

    status = commands.add_parser("status", help="inspect process and Git state after reconnect")
    status.add_argument("--repo", required=True)
    status.add_argument("--branch", required=True)
    status.add_argument("--state-dir", required=True)
    status.add_argument("--main-ref", default="origin/main")

    reconcile = commands.add_parser("reconcile", help="recognize branch merge or external main advance from Git")
    reconcile.add_argument("--repo", required=True)
    reconcile.add_argument("--branch", required=True)
    reconcile.add_argument("--base-sha", required=True)
    reconcile.add_argument("--main-ref", default="origin/main")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(sys.argv[1:] if argv is None else argv)
    try:
        if args.operation == "materialize":
            result = materialize_prompt(
                repo_path=args.repo,
                control_sha=args.control_sha,
                manifest_path=args.manifest,
                task_id=args.task,
                task_order=[part.strip() for part in args.task_order.split(",") if part.strip()],
                start_main_sha=args.start_main_sha,
                output_path=args.output,
                host_profile=args.host_profile,
                execution_channel=args.execution_channel,
                continuation_from=args.continuation_from,
                continuation_state_file=args.continuation_state_file,
            )
        elif args.operation == "start":
            result = start_run(
                repo_path=args.repo,
                branch=args.branch,
                run_id=args.run_id,
                prompt_file=args.prompt_file,
                state_dir=args.state_dir,
                control_sha=args.control_sha,
                task_id=args.task,
                continuation_from=args.continuation_from,
                codex_bin=args.codex_bin,
                main_ref=args.main_ref,
            )
        elif args.operation == "status":
            result = status_run(
                repo_path=args.repo,
                branch=args.branch,
                state_dir=args.state_dir,
                main_ref=args.main_ref,
            )
        else:
            result = reconcile_git(
                repo_path=args.repo,
                branch=args.branch,
                base_sha=args.base_sha,
                main_ref=args.main_ref,
            )
    except (RecoveryError, codex_session.SessionError) as exc:
        print(json.dumps({"status": "invalid", "error": str(exc)}, sort_keys=True))
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    if result.get("status") in {
        "invalid",
        "blocked",
        "already_running",
        "continuation_required",
        "failed",
        "already_merged",
        "external_main_advance",
        "branch_diverged",
        "main_diverged",
        "main_ref_missing",
        "branch_missing",
        "seed_missing",
        "seed_only_merged",
    }:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
