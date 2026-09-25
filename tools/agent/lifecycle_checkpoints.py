#!/usr/bin/env python3
"""Read-only assignment checks and atomic lifecycle checkpoints for local Git work."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any

PHASES = (
    "preflight_ok",
    "seeded",
    "implementation_ready",
    "focused_green",
    "canonical_green",
    "review_written",
    "pr_open",
    "ci_green",
    "merged",
)
_PHASE_RANK = {phase: index for index, phase in enumerate(PHASES)}
_SHA_RE = re.compile(r"^[0-9a-fA-F]{40,64}$")
_SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_TASK_HEADING_RE = re.compile(
    r"^###\s+([0-9]{4})\s+" + re.escape(chr(0x2014)) + r"\s*(.*?)\s*$"
)
_ORDERED_TASK_RE = re.compile(
    r"^([0-9]+)\.\s+([0-9]{4})\s+" + re.escape(chr(0x2014)) + r"\s*(.*?)\s*$"
)
_TASK_PATH_RE = re.compile(r"^([0-9]{4})-[^/]+\.md$")


class LifecycleError(Exception):
    """An expected validation, state, or local Git error."""


def _utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )


def _valid_sha(value: str | None) -> bool:
    return isinstance(value, str) and bool(_SHA_RE.fullmatch(value))


def _valid_timestamp(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None


def _safe_name(value: str, label: str) -> str:
    if not _SAFE_NAME_RE.fullmatch(value) or value in {".", ".."}:
        raise LifecycleError(f"{label} must be 1-128 safe filename characters")
    return value


def _safe_relative_path(value: str, label: str) -> str:
    if not value or "\\" in value:
        raise LifecycleError(f"{label} must be a safe repository-relative path")
    path = PurePosixPath(value)
    if path.is_absolute() or path.as_posix() == "." or any(
        part in {"", ".", ".."} for part in path.parts
    ):
        raise LifecycleError(f"{label} must be a safe repository-relative path")
    return path.as_posix()


def _git_raw(repo: Path, *args: str) -> subprocess.CompletedProcess[bytes]:
    environment = os.environ.copy()
    environment["GIT_OPTIONAL_LOCKS"] = "0"
    environment["GIT_TERMINAL_PROMPT"] = "0"
    try:
        return subprocess.run(
            ["git", "-C", str(repo), *args],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=15,
            env=environment,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise LifecycleError(f"local git command failed: {args[0] if args else 'git'}") from exc


def _git(repo: Path, *args: str) -> str:
    result = _git_raw(repo, *args)
    if result.returncode:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise LifecycleError(f"git {args[0]} failed: {detail[:300]}")
    return result.stdout.decode("utf-8", errors="strict").strip()


def _ref_sha(repo: Path, ref: str) -> str | None:
    result = _git_raw(repo, "rev-parse", "--verify", f"{ref}^{{commit}}")
    if result.returncode:
        return None
    value = result.stdout.decode("ascii", errors="replace").strip()
    return value if _valid_sha(value) else None


def _ref_exists(repo: Path, ref: str) -> bool:
    return _git_raw(repo, "show-ref", "--verify", "--quiet", ref).returncode == 0


def _check(name: str, ok: bool, *, actual: Any = None, expected: Any = None) -> dict[str, Any]:
    value: dict[str, Any] = {"name": name, "ok": bool(ok)}
    if actual is not None:
        value["actual"] = actual
    if expected is not None:
        value["expected"] = expected
    return value


def _inline_field(lines: list[str], key: str) -> str | None:
    prefix = f"{key}:"
    for line in lines:
        stripped = line.strip()
        if not stripped.startswith(prefix):
            continue
        value = stripped[len(prefix) :].strip()
        if len(value) >= 2 and value[0] == chr(96) and value[-1] == chr(96):
            value = value[1:-1]
        return value
    return None


def _manifest_field(lines: list[str], key: str) -> str | None:
    prefix = f"{key}:"
    for index, line in enumerate(lines):
        stripped = line.strip()
        if not stripped.startswith(prefix):
            continue
        value = stripped[len(prefix) :].strip()
        if not value:
            for candidate in lines[index + 1 :]:
                value = candidate.strip()
                if value:
                    break
        if len(value) >= 2 and value[0] == chr(96) and value[-1] == chr(96):
            value = value[1:-1]
        return value or None
    return None


def _manifest_section(lines: list[str], heading: str) -> list[str]:
    marker = f"## {heading}"
    try:
        start = next(index for index, line in enumerate(lines) if line.strip() == marker)
    except StopIteration:
        return []
    end = next(
        (index for index in range(start + 1, len(lines)) if lines[index].startswith("## ")),
        len(lines),
    )
    return lines[start + 1 : end]


def _backtick_bullets(lines: list[str], label: str) -> list[str]:
    try:
        start = next(index for index, line in enumerate(lines) if line.strip() == label)
    except StopIteration:
        return []
    values: list[str] = []
    for line in lines[start + 1 :]:
        stripped = line.strip()
        if not stripped:
            continue
        match = re.fullmatch(r"-\s+`([^`]+)`", stripped)
        if not match:
            break
        values.append(match.group(1))
    return values


def _task_id_from_path(path: str, label: str) -> str:
    name = PurePosixPath(path).name
    match = _TASK_PATH_RE.fullmatch(name)
    if not match:
        raise LifecycleError(f"{label} must have a four-digit task ID filename prefix")
    return match.group(1)


def _parse_integrated_manifest(lines: list[str]) -> dict[str, Any]:
    required_fields = {
        "batch_id": _manifest_field(lines, "Batch ID"),
        "expected_start_main_sha": _manifest_field(lines, "Expected start main"),
        "implementation_branch": _manifest_field(lines, "Implementation branch"),
        "execution_user": _manifest_field(lines, "Execution user"),
        "workdir": _manifest_field(lines, "Required work directory"),
        "review_destination": _manifest_field(lines, "Batch review destination"),
        "full_local": _manifest_field(lines, "Full local regression"),
    }
    missing = [name for name, value in required_fields.items() if not value]
    if missing:
        raise LifecycleError(f"integrated manifest is missing required fields: {', '.join(missing)}")
    start_sha = required_fields["expected_start_main_sha"]
    assert start_sha is not None
    if not _valid_sha(start_sha):
        raise LifecycleError("integrated manifest expected start main SHA is invalid")
    branch = required_fields["implementation_branch"]
    assert branch is not None
    if not branch.strip() or any(character.isspace() for character in branch):
        raise LifecycleError("integrated manifest implementation branch is invalid")
    workdir = required_fields["workdir"]
    assert workdir is not None
    if not PurePosixPath(workdir).is_absolute():
        raise LifecycleError("integrated manifest workdir must be absolute")
    review_destination = _safe_relative_path(
        required_fields["review_destination"] or "", "batch review destination"
    )
    full_local_match = re.fullmatch(
        r"full_local_required:\s*(true|false)", required_fields["full_local"] or ""
    )
    if not full_local_match:
        raise LifecycleError("integrated manifest full local regression is malformed")

    ordered_lines = _manifest_section(lines, "Ordered tasks")
    ordered: list[tuple[int, str, str]] = []
    for line in ordered_lines:
        match = _ORDERED_TASK_RE.fullmatch(line.strip())
        if match:
            position, task_id, title = match.groups()
            ordered.append((int(position), task_id, title))
    specs = [
        _safe_relative_path(path, "spec source")
        for path in _backtick_bullets(ordered_lines, "Exact task specs:")
    ]
    destinations = [
        _safe_relative_path(path, "assignment destination")
        for path in _backtick_bullets(ordered_lines, "Seed destinations:")
    ]
    ordered_ids = [task_id for _position, task_id, _title in ordered]
    spec_ids = [_task_id_from_path(path, "spec source") for path in specs]
    destination_ids = [
        _task_id_from_path(path, "assignment destination") for path in destinations
    ]
    if not ordered:
        raise LifecycleError("integrated manifest has no ordered tasks")
    if len(ordered_ids) != len(set(ordered_ids)):
        raise LifecycleError("integrated manifest contains duplicate ordered task IDs")
    if [position for position, _task_id, _title in ordered] != list(
        range(1, len(ordered) + 1)
    ):
        raise LifecycleError("integrated manifest task positions are contradictory")
    if any(not title for _position, _task_id, title in ordered):
        raise LifecycleError("integrated manifest contains an empty task title")
    if len(spec_ids) != len(set(spec_ids)) or len(destination_ids) != len(set(destination_ids)):
        raise LifecycleError("integrated manifest contains duplicate task paths")
    if not (ordered_ids == spec_ids == destination_ids):
        raise LifecycleError(
            "integrated manifest ordered tasks, specs, and seed destinations must align exactly"
        )
    tasks = [
        {
            "position": position,
            "id": task_id,
            "title": title,
            "branch": branch,
            "spec_source": specs[position - 1],
            "assignment_destination": destinations[position - 1],
        }
        for position, (_declared_position, task_id, title) in enumerate(ordered, start=1)
    ]
    return {
        "format": "integrated_v8",
        "mode": "integrated_batch",
        "batch_id": required_fields["batch_id"],
        "expected_start_main_sha": start_sha,
        "implementation_branch": branch,
        "execution_user": required_fields["execution_user"],
        "workdir": workdir,
        "review_destination": review_destination,
        "full_local_required": full_local_match.group(1) == "true",
        "tasks": tasks,
    }


def _parse_legacy_manifest(lines: list[str]) -> dict[str, Any]:
    batch_id = _inline_field(lines, "Batch ID")
    tasks: list[dict[str, Any]] = []
    for index, line in enumerate(lines):
        match = _TASK_HEADING_RE.fullmatch(line.strip())
        if not match:
            continue
        end = len(lines)
        for next_index in range(index + 1, len(lines)):
            if lines[next_index].startswith("## "):
                end = next_index
                break
            if lines[next_index].startswith("### "):
                end = next_index
                break
        block = lines[index + 1 : end]
        task_id, title = match.groups()
        branch = _inline_field(block, "Branch")
        spec_source = _inline_field(block, "Spec source")
        assignment_destination = _inline_field(block, "Assignment destination")
        depends_on = _inline_field(block, "Depends on")
        if not branch or not spec_source or not assignment_destination:
            raise LifecycleError(f"manifest task {task_id} is missing required fields")
        branch = branch
        spec_source = _safe_relative_path(spec_source, "spec source")
        assignment_destination = _safe_relative_path(
            assignment_destination, "assignment destination"
        )
        task: dict[str, Any] = {
            "position": len(tasks) + 1,
            "id": task_id,
            "title": title,
            "branch": branch,
            "spec_source": spec_source,
            "assignment_destination": assignment_destination,
        }
        if depends_on:
            task["depends_on"] = depends_on
        tasks.append(task)

    ids = [task["id"] for task in tasks]
    if not tasks or len(ids) != len(set(ids)):
        raise LifecycleError("manifest has no tasks or contains duplicate task IDs")
    branches = [task["branch"] for task in tasks]
    if len(branches) != len(set(branches)):
        raise LifecycleError("manifest contains duplicate task branches")
    return {"format": "legacy", "mode": "per_task", "batch_id": batch_id, "tasks": tasks}


def parse_manifest(manifest_text: str) -> dict[str, Any]:
    lines = manifest_text.splitlines()
    if any(
        line.strip() in {"## Ordered tasks", "Exact task specs:", "Seed destinations:"}
        for line in lines
    ):
        return _parse_integrated_manifest(lines)
    return _parse_legacy_manifest(lines)


def _object_blob(repo: Path, commit: str, path: str) -> bytes:
    safe_path = _safe_relative_path(path, "Git object path")
    if not _valid_sha(commit):
        raise LifecycleError("control or seed SHA is invalid")
    result = _git_raw(repo, "cat-file", "blob", f"{commit}:{safe_path}")
    if result.returncode:
        raise LifecycleError(f"blob is missing at the requested SHA: {safe_path}")
    return result.stdout


def _repo_root(repo_path: str) -> Path:
    requested = Path(repo_path).expanduser().resolve()
    if not requested.is_dir():
        raise LifecycleError("repository path is not an existing directory")
    actual = Path(_git(requested, "rev-parse", "--show-toplevel")).resolve()
    if actual != requested:
        raise LifecycleError("repository path must name the Git worktree root")
    return actual


def _add_git_check(
    checks: list[dict[str, Any]],
    name: str,
    repo: Path,
    *args: str,
    expected: str | None = None,
) -> str | None:
    try:
        actual = _git(repo, *args)
    except LifecycleError as exc:
        checks.append({"name": name, "ok": False, "error": str(exc)})
        return None
    checks.append(_check(name, expected is None or actual == expected, actual=actual, expected=expected))
    return actual


def check_preflight(
    *,
    repo_path: str,
    control_branch: str,
    control_sha: str,
    manifest_path: str,
    task_id: str,
    remote: str = "origin",
    expected_repo_path: str | None = None,
    expected_origin: str | None = None,
    expected_branch: str | None = "main",
    expected_start_main_sha: str | None = None,
    expected_task_order: list[str] | None = None,
    expected_task_spec_source: str | None = None,
    expected_assignment_destination: str | None = None,
    allow_existing_task_branch: bool = False,
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    try:
        repo = _repo_root(repo_path)
    except LifecycleError as exc:
        return {
            "status": "invalid",
            "ok": False,
            "checks": [{"name": "repository_path", "ok": False, "error": str(exc)}],
            "tasks": [],
        }

    requested = Path(expected_repo_path or repo_path).expanduser().resolve()
    checks.append(_check("repository_identity", repo == requested, actual=str(repo), expected=str(requested)))
    branch = _add_git_check(checks, "current_branch", repo, "branch", "--show-current", expected=expected_branch)
    porcelain = _add_git_check(
        checks,
        "worktree_clean",
        repo,
        "status",
        "--porcelain=v1",
        "--untracked-files=all",
    )
    checks[-1]["actual"] = "clean" if porcelain == "" else "dirty"
    checks[-1]["ok"] = porcelain == ""

    origin_url: str | None
    try:
        origin_url = _git(repo, "remote", "get-url", remote)
        checks.append(
            _check(
                "repository_remote",
                expected_origin is None or origin_url == expected_origin,
                actual=origin_url,
                expected=expected_origin,
            )
        )
    except LifecycleError as exc:
        origin_url = None
        checks.append({"name": "repository_remote", "ok": False, "error": str(exc)})

    main_sha = _ref_sha(repo, "refs/heads/main")
    upstream_sha = _ref_sha(repo, f"refs/remotes/{remote}/main")
    checks.append(_check("local_main_exists", main_sha is not None, actual=main_sha))
    checks.append(_check("fetched_origin_main_exists", upstream_sha is not None, actual=upstream_sha))
    checks.append(
        _check(
            "main_matches_fetched_origin",
            main_sha is not None and main_sha == upstream_sha,
            actual={"main": main_sha, f"{remote}/main": upstream_sha},
            expected="equal",
        )
    )
    if expected_start_main_sha is not None:
        expected_valid = _valid_sha(expected_start_main_sha)
        checks.append(_check("expected_start_sha_valid", expected_valid, actual=expected_start_main_sha))
        checks.append(
            _check(
                "expected_start_main",
                expected_valid and main_sha == expected_start_main_sha and upstream_sha == expected_start_main_sha,
                actual={"main": main_sha, f"{remote}/main": upstream_sha},
                expected=expected_start_main_sha,
            )
        )

    control_ref_ok = _git_raw(repo, "check-ref-format", f"refs/heads/{control_branch}").returncode == 0
    remote_ok = bool(re.fullmatch(r"[A-Za-z0-9._-]+", remote))
    checks.append(_check("control_ref_format", control_ref_ok and remote_ok, actual=control_branch))
    local_control_ref = f"refs/heads/{control_branch}"
    fetched_control_ref = f"refs/remotes/{remote}/{control_branch}"
    local_control_sha = _ref_sha(repo, local_control_ref) if control_ref_ok else None
    fetched_control_sha = _ref_sha(repo, fetched_control_ref) if control_ref_ok and remote_ok else None
    checks.append(
        _check(
            "control_branch_fetched",
            fetched_control_sha is not None,
            actual={"local": local_control_sha, "fetched_remote": fetched_control_sha},
            expected="fetched remote-tracking ref exists",
        )
    )
    checks.append(
        _check(
            "control_branch_sha",
            _valid_sha(control_sha)
            and fetched_control_sha == control_sha
            and (local_control_sha is None or local_control_sha == control_sha),
            actual={"local": local_control_sha, "fetched_remote": fetched_control_sha},
            expected=control_sha,
        )
    )
    commit_exists = _valid_sha(control_sha) and _git_raw(
        repo, "cat-file", "-e", f"{control_sha}^{{commit}}"
    ).returncode == 0
    checks.append(_check("control_commit_exists", commit_exists, actual=control_sha))

    manifest_text: str | None = None
    manifest_data: dict[str, Any] | None = None
    try:
        manifest_bytes = _object_blob(repo, control_sha, manifest_path)
        manifest_text = manifest_bytes.decode("utf-8")
        manifest_data = parse_manifest(manifest_text)
        checks.append(
            _check(
                "manifest_at_control_sha",
                True,
                actual={
                    "path": manifest_path,
                    "batch_id": manifest_data["batch_id"],
                    "format": manifest_data["format"],
                    "mode": manifest_data["mode"],
                },
            )
        )
        checks.append(
            _check(
                "manifest_task_order",
                expected_task_order is None
                or [task["id"] for task in manifest_data["tasks"]] == expected_task_order,
                actual=[task["id"] for task in manifest_data["tasks"]],
                expected=expected_task_order,
            )
        )
        if manifest_data["format"] == "integrated_v8":
            manifest_start = manifest_data["expected_start_main_sha"]
            checks.append(
                _check(
                    "manifest_start_main",
                    main_sha == upstream_sha == manifest_start
                    and (
                        expected_start_main_sha is None
                        or expected_start_main_sha == manifest_start
                    ),
                    actual={
                        "manifest": manifest_start,
                        "argument": expected_start_main_sha,
                        "main": main_sha,
                        f"{remote}/main": upstream_sha,
                    },
                    expected=manifest_start,
                )
            )
            implementation_branch = manifest_data["implementation_branch"]
            branch_valid = (
                _git_raw(
                    repo,
                    "check-ref-format",
                    f"refs/heads/{implementation_branch}",
                ).returncode
                == 0
            )
            checks.append(
                _check(
                    "manifest_implementation_branch",
                    branch_valid
                    and all(
                        task["branch"] == implementation_branch
                        for task in manifest_data["tasks"]
                    ),
                    actual=implementation_branch,
                    expected="one valid shared implementation branch",
                )
            )
            missing_specs = [
                task["spec_source"]
                for task in manifest_data["tasks"]
                if _git_raw(
                    repo,
                    "cat-file",
                    "-e",
                    f"{control_sha}:{task['spec_source']}",
                ).returncode
                != 0
            ]
            checks.append(
                _check(
                    "manifest_task_specs_at_control_sha",
                    not missing_specs,
                    actual=missing_specs or "all present",
                    expected="all ordered exact task specs present",
                )
            )
    except (LifecycleError, UnicodeError) as exc:
        checks.append({"name": "manifest_at_control_sha", "ok": False, "error": str(exc)})

    tasks = manifest_data["tasks"] if manifest_data else []
    selected = next((task for task in tasks if task["id"] == task_id), None)
    checks.append(_check("selected_task_exists", selected is not None, actual=task_id))
    if selected is not None:
        checks.append(
            _check(
                "task_spec_source_matches",
                expected_task_spec_source is None or selected["spec_source"] == expected_task_spec_source,
                actual=selected["spec_source"],
                expected=expected_task_spec_source,
            )
        )
        checks.append(
            _check(
                "assignment_destination_matches",
                expected_assignment_destination is None
                or selected["assignment_destination"] == expected_assignment_destination,
                actual=selected["assignment_destination"],
                expected=expected_assignment_destination,
            )
        )
        try:
            _object_blob(repo, control_sha, selected["spec_source"])
            checks.append(
                _check(
                    "task_spec_at_control_sha",
                    True,
                    actual={"task_id": task_id, "path": selected["spec_source"]},
                )
            )
        except LifecycleError as exc:
            checks.append({"name": "task_spec_at_control_sha", "ok": False, "error": str(exc)})

        branch_ref_ok = _git_raw(repo, "check-ref-format", f"refs/heads/{selected['branch']}").returncode == 0
        local_target = _ref_sha(repo, f"refs/heads/{selected['branch']}") if branch_ref_ok else None
        remote_target = (
            _ref_sha(repo, f"refs/remotes/{remote}/{selected['branch']}")
            if branch_ref_ok and remote_ok
            else None
        )
        exists = local_target is not None or remote_target is not None
        checks.append(
            _check(
                "target_task_branch",
                branch_ref_ok and (allow_existing_task_branch or not exists),
                actual={
                    "branch": selected["branch"],
                    "local": local_target,
                    "fetched_remote": remote_target,
                    "allowed_existing": allow_existing_task_branch,
                },
                expected="absent unless explicitly allowed",
            )
        )

    result: dict[str, Any] = {
        "status": "ok" if all(check["ok"] for check in checks) else "blocked",
        "ok": all(check["ok"] for check in checks),
        "repository": str(repo),
        "current_branch": branch,
        "main_sha": main_sha,
        "origin_main_sha": upstream_sha,
        "control_branch": control_branch,
        "control_sha": control_sha,
        "manifest_path": manifest_path,
        "manifest_format": manifest_data["format"] if manifest_data else None,
        "manifest_mode": manifest_data["mode"] if manifest_data else None,
        "batch_id": manifest_data["batch_id"] if manifest_data else None,
        "tasks": tasks,
        "selected_task": selected,
        "checks": checks,
    }
    return result


def verify_seed(
    *,
    repo_path: str,
    branch: str,
    base_sha: str,
    control_sha: str,
    assignment_source: str,
    assignment_destination: str,
    seed_sha: str | None = None,
    allow_later_head: bool = False,
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    try:
        repo = _repo_root(repo_path)
    except LifecycleError as exc:
        return {
            "status": "invalid",
            "ok": False,
            "checks": [{"name": "repository_path", "ok": False, "error": str(exc)}],
        }

    actual_branch = _add_git_check(
        checks,
        "task_branch",
        repo,
        "branch",
        "--show-current",
        expected=branch,
    )
    porcelain = _add_git_check(
        checks,
        "worktree_clean",
        repo,
        "status",
        "--porcelain=v1",
        "--untracked-files=all",
    )
    checks[-1]["actual"] = "clean" if porcelain == "" else "dirty"
    checks[-1]["ok"] = porcelain == ""
    head = _add_git_check(checks, "head_exists", repo, "rev-parse", "--verify", "HEAD")
    selected_seed = seed_sha or head
    checks.append(
        _check(
            "base_sha_valid",
            _valid_sha(base_sha) and _ref_sha(repo, base_sha) == base_sha,
            actual=base_sha,
        )
    )
    checks.append(
        _check(
            "control_sha_valid",
            _valid_sha(control_sha) and _ref_sha(repo, control_sha) == control_sha,
            actual=control_sha,
        )
    )
    if not _valid_sha(selected_seed):
        checks.append(_check("seed_sha_valid", False, actual=selected_seed))
        return {
            "status": "invalid",
            "ok": False,
            "branch": actual_branch,
            "head": head,
            "seed_sha": selected_seed,
            "checks": checks,
        }

    checks.append(_check("seed_sha_valid", _ref_sha(repo, selected_seed) == selected_seed, actual=selected_seed))
    checks.append(
        _check(
            "seed_is_head",
            allow_later_head or selected_seed == head,
            actual=head,
            expected=selected_seed if not allow_later_head else "seed is an ancestor of HEAD",
        )
    )
    if allow_later_head:
        ancestor = _git_raw(repo, "merge-base", "--is-ancestor", selected_seed, head or "")
        checks.append(_check("seed_ancestor", ancestor.returncode == 0, actual=selected_seed, expected=head))
    parents_result = _git_raw(repo, "rev-list", "--parents", "-n", "1", selected_seed)
    parent_fields = parents_result.stdout.decode("ascii", errors="replace").strip().split()
    parent_sha = parent_fields[1] if len(parent_fields) == 2 else None
    checks.append(_check("ordinary_single_parent_seed", parents_result.returncode == 0 and len(parent_fields) == 2, actual=parent_fields))
    checks.append(_check("seed_parent_is_base", parent_sha == base_sha, actual=parent_sha, expected=base_sha))
    count_result = _git_raw(repo, "rev-list", "--count", f"{base_sha}..{selected_seed}")
    count = count_result.stdout.decode("ascii", errors="replace").strip() if count_result.returncode == 0 else None
    checks.append(_check("one_seed_commit_above_base", count == "1", actual=count, expected="1"))

    try:
        source_bytes = _object_blob(repo, control_sha, assignment_source)
        destination_bytes = _object_blob(repo, selected_seed, assignment_destination)
        checks.append(
            _check(
                "assignment_bytes_match_control",
                source_bytes == destination_bytes,
                actual={"control_path": assignment_source, "branch_path": assignment_destination},
                expected="byte-identical",
            )
        )
    except LifecycleError as exc:
        checks.append({"name": "assignment_bytes_match_control", "ok": False, "error": str(exc)})

    return {
        "status": "verified" if all(check["ok"] for check in checks) else "blocked",
        "ok": all(check["ok"] for check in checks),
        "branch": actual_branch,
        "head": head,
        "seed_sha": selected_seed,
        "base_sha": base_sha,
        "checks": checks,
    }


def verify_batch_seed(
    *,
    repo_path: str,
    control_sha: str,
    manifest_path: str,
    seed_sha: str | None = None,
    allow_later_head: bool = False,
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    try:
        repo = _repo_root(repo_path)
        manifest_bytes = _object_blob(repo, control_sha, manifest_path)
        manifest = parse_manifest(manifest_bytes.decode("utf-8"))
        if manifest["format"] != "integrated_v8":
            raise LifecycleError("batch seed verification requires an integrated-v8 manifest")
    except (LifecycleError, UnicodeError) as exc:
        return {
            "status": "invalid",
            "ok": False,
            "checks": [{"name": "batch_manifest", "ok": False, "error": str(exc)}],
        }

    branch = _add_git_check(
        checks,
        "implementation_branch",
        repo,
        "branch",
        "--show-current",
        expected=manifest["implementation_branch"],
    )
    porcelain = _add_git_check(
        checks,
        "worktree_clean",
        repo,
        "status",
        "--porcelain=v1",
        "--untracked-files=all",
    )
    checks[-1]["actual"] = "clean" if porcelain == "" else "dirty"
    checks[-1]["ok"] = porcelain == ""
    head = _add_git_check(checks, "head_exists", repo, "rev-parse", "--verify", "HEAD")
    selected_seed = seed_sha or head
    if not _valid_sha(selected_seed) or _ref_sha(repo, selected_seed or "") != selected_seed:
        checks.append(_check("seed_sha_valid", False, actual=selected_seed))
        return {
            "status": "invalid",
            "ok": False,
            "branch": branch,
            "head": head,
            "seed_sha": selected_seed,
            "checks": checks,
        }
    checks.append(_check("seed_sha_valid", True, actual=selected_seed))
    start_sha = manifest["expected_start_main_sha"]
    parent_line = _git_raw(repo, "rev-list", "--parents", "-n", "1", selected_seed)
    parent_fields = parent_line.stdout.decode("ascii", errors="replace").strip().split()
    parent_sha = parent_fields[1] if len(parent_fields) == 2 else None
    checks.append(
        _check(
            "seed_parent_is_expected_start",
            parent_line.returncode == 0 and len(parent_fields) == 2 and parent_sha == start_sha,
            actual=parent_sha,
            expected=start_sha,
        )
    )
    if allow_later_head:
        ancestor = _git_raw(repo, "merge-base", "--is-ancestor", selected_seed, head or "")
        checks.append(
            _check("seed_ancestor", ancestor.returncode == 0, actual=selected_seed, expected=head)
        )
    else:
        checks.append(_check("seed_is_head", selected_seed == head, actual=head, expected=selected_seed))

    try:
        seed_manifest = _object_blob(repo, selected_seed, manifest_path)
        checks.append(
            _check(
                "active_manifest_bytes_match_control",
                seed_manifest == manifest_bytes,
                actual=manifest_path,
                expected="byte-identical",
            )
        )
    except LifecycleError as exc:
        checks.append(
            {"name": "active_manifest_bytes_match_control", "ok": False, "error": str(exc)}
        )

    material: list[dict[str, Any]] = []
    for task in manifest["tasks"]:
        try:
            source = _object_blob(repo, control_sha, task["spec_source"])
            destination = _object_blob(repo, selected_seed, task["assignment_destination"])
            matches = source == destination
            material.append(
                {
                    "id": task["id"],
                    "spec_source": task["spec_source"],
                    "assignment_destination": task["assignment_destination"],
                    "ok": matches,
                }
            )
        except LifecycleError as exc:
            material.append(
                {
                    "id": task["id"],
                    "spec_source": task["spec_source"],
                    "assignment_destination": task["assignment_destination"],
                    "ok": False,
                    "error": str(exc),
                }
            )
    checks.append(
        _check(
            "complete_batch_material",
            len(material) == len(manifest["tasks"]) and all(item["ok"] for item in material),
            actual=material,
            expected="all ordered task specs copied byte-for-byte",
        )
    )
    return {
        "status": "verified" if all(check["ok"] for check in checks) else "blocked",
        "ok": all(check["ok"] for check in checks),
        "batch_id": manifest["batch_id"],
        "branch": branch,
        "head": head,
        "seed_sha": selected_seed,
        "start_main_sha": start_sha,
        "task_order": [task["id"] for task in manifest["tasks"]],
        "checks": checks,
    }


def _repo_and_state(repo_path: str, state_dir: str) -> tuple[Path, Path, str, str, bool]:
    repo = _repo_root(repo_path)
    branch = _git(repo, "branch", "--show-current")
    head = _git(repo, "rev-parse", "--verify", "HEAD")
    if not branch or not _valid_sha(head):
        raise LifecycleError("checkpoint requires an attached branch and valid HEAD")
    status = _git(repo, "status", "--porcelain=v1", "--untracked-files=all")
    state = Path(state_dir).expanduser().resolve()
    try:
        state.relative_to(repo)
    except ValueError:
        pass
    else:
        raise LifecycleError("checkpoint state directory must be outside the repository worktree")
    return repo, state, branch, head, status == ""


def _checkpoint_path(state: Path, assignment: str, *, create: bool) -> Path:
    safe_assignment = _safe_name(assignment, "assignment")
    directory = state / "lifecycle-checkpoints"
    if directory.is_symlink():
        raise LifecycleError("checkpoint directory must not be a symlink")
    if create:
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = directory / f"{safe_assignment}.json"
    if path.is_symlink():
        raise LifecycleError("checkpoint file must not be a symlink")
    try:
        path.resolve().relative_to(state)
    except ValueError as exc:
        raise LifecycleError("checkpoint path escaped the state directory") from exc
    return path


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
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        directory_fd = os.open(path.parent, flags)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def _load_checkpoint(path: Path) -> dict[str, Any]:
    if path.is_symlink():
        raise LifecycleError("checkpoint file must not be a symlink")
    try:
        with path.open("r", encoding="utf-8") as stream:
            checkpoint = json.load(stream)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise LifecycleError("checkpoint JSON is missing or malformed") from exc
    if not isinstance(checkpoint, dict):
        raise LifecycleError("checkpoint JSON must be an object")
    _validate_checkpoint(checkpoint)
    return checkpoint


def _validate_checkpoint(checkpoint: dict[str, Any]) -> None:
    required = {"schema_version", "assignment", "branch", "repo_path", "head", "phase", "highest_phase", "correction_iteration", "phase_history", "updated_at"}
    if not required.issubset(checkpoint):
        raise LifecycleError("checkpoint is missing required fields")
    schema_version = checkpoint.get("schema_version")
    if not isinstance(schema_version, int) or isinstance(schema_version, bool) or schema_version != 1:
        raise LifecycleError("checkpoint schema version is invalid")
    if not isinstance(checkpoint.get("assignment"), str) or not _SAFE_NAME_RE.fullmatch(checkpoint["assignment"]):
        raise LifecycleError("checkpoint assignment is invalid")
    if not isinstance(checkpoint.get("branch"), str) or not checkpoint["branch"]:
        raise LifecycleError("checkpoint branch is invalid")
    if not isinstance(checkpoint.get("repo_path"), str) or not checkpoint["repo_path"]:
        raise LifecycleError("checkpoint repository path is invalid")
    if not _valid_sha(checkpoint.get("head")):
        raise LifecycleError("checkpoint HEAD is invalid")
    phase = checkpoint.get("phase")
    highest_phase = checkpoint.get("highest_phase")
    if (
        not isinstance(phase, str)
        or phase not in _PHASE_RANK
        or not isinstance(highest_phase, str)
        or highest_phase not in _PHASE_RANK
    ):
        raise LifecycleError("checkpoint phase is invalid")
    if not isinstance(checkpoint.get("worktree_clean"), bool):
        raise LifecycleError("checkpoint worktree status is invalid")
    iteration = checkpoint.get("correction_iteration")
    if not isinstance(iteration, int) or isinstance(iteration, bool) or iteration < 0:
        raise LifecycleError("checkpoint correction iteration is invalid")
    history = checkpoint.get("phase_history")
    if not isinstance(history, list) or not history:
        raise LifecycleError("checkpoint phase history is invalid")
    maximum = -1
    previous_event: dict[str, Any] | None = None
    for event in history:
        if (
            not isinstance(event, dict)
            or not isinstance(event.get("phase"), str)
            or event.get("phase") not in _PHASE_RANK
        ):
            raise LifecycleError("checkpoint phase history contains an invalid event")
        if not _valid_sha(event.get("head")):
            raise LifecycleError("checkpoint phase history contains an invalid HEAD")
        event_iteration = event.get("correction_iteration")
        if not isinstance(event_iteration, int) or isinstance(event_iteration, bool) or event_iteration < 0:
            raise LifecycleError("checkpoint phase history has an invalid correction iteration")
        if not _valid_timestamp(event.get("timestamp")):
            raise LifecycleError("checkpoint phase history has an invalid timestamp")
        if previous_event is None:
            if event_iteration != 0:
                raise LifecycleError("checkpoint history must begin at correction iteration 0")
        else:
            previous_iteration = previous_event["correction_iteration"]
            if event_iteration not in {previous_iteration, previous_iteration + 1}:
                raise LifecycleError("checkpoint history correction iterations are not sequential")
            previous_phase = previous_event["phase"]
            if previous_phase == "merged" and event["phase"] != "merged":
                raise LifecycleError("checkpoint history regresses after merge")
            if (
                _PHASE_RANK[event["phase"]] < _PHASE_RANK[previous_phase]
                and event_iteration != previous_iteration + 1
            ):
                raise LifecycleError("checkpoint history regresses without a correction iteration")
        maximum = max(maximum, _PHASE_RANK[event["phase"]])
        previous_event = event
    if _PHASE_RANK[highest_phase] != maximum:
        raise LifecycleError("checkpoint highest_phase does not match its history")
    if (
        history[-1].get("phase") != phase
        or history[-1].get("correction_iteration") != iteration
        or history[-1].get("head") != checkpoint["head"]
    ):
        raise LifecycleError("checkpoint final history event does not match its current state")
    if not _valid_timestamp(checkpoint.get("updated_at")):
        raise LifecycleError("checkpoint timestamp is invalid")
    if "pr_number" in checkpoint and (
        not isinstance(checkpoint["pr_number"], int)
        or isinstance(checkpoint["pr_number"], bool)
        or checkpoint["pr_number"] <= 0
    ):
        raise LifecycleError("checkpoint PR number is invalid")
    for name in ("pr_head_sha", "merge_sha"):
        if name in checkpoint and not _valid_sha(checkpoint[name]):
            raise LifecycleError(f"checkpoint {name} is invalid")
    if _PHASE_RANK[phase] >= _PHASE_RANK["pr_open"]:
        if "pr_number" not in checkpoint or "pr_head_sha" not in checkpoint:
            raise LifecycleError("PR checkpoint is missing its number or head SHA")
        if checkpoint["pr_head_sha"] != checkpoint["head"]:
            raise LifecycleError("PR head SHA does not match checkpoint HEAD")
    if phase == "merged":
        if "merge_sha" not in checkpoint:
            raise LifecycleError("merged checkpoint is missing its merge SHA")
    elif "merge_sha" in checkpoint:
        raise LifecycleError("merge SHA is only valid at the merged phase")
    corrections = checkpoint.get("correction_history", [])
    if not isinstance(corrections, list):
        raise LifecycleError("checkpoint correction history is invalid")
    if len(corrections) != iteration:
        raise LifecycleError("checkpoint correction history does not match its iteration")
    correction_transitions: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for previous, current in zip(history, history[1:]):
        if current["correction_iteration"] == previous["correction_iteration"] + 1:
            correction_transitions.append((previous, current))
    if len(correction_transitions) != len(corrections):
        raise LifecycleError("checkpoint correction history does not match phase history")
    for expected_iteration, (correction, transition) in enumerate(
        zip(corrections, correction_transitions), start=1
    ):
        previous, current = transition
        if (
            not isinstance(correction, dict)
            or not isinstance(correction.get("iteration"), int)
            or isinstance(correction.get("iteration"), bool)
            or correction.get("iteration") != expected_iteration
            or not _valid_timestamp(correction.get("started_at"))
            or correction.get("from_phase") != previous["phase"]
            or correction.get("phase") != current["phase"]
            or correction.get("head") != current["head"]
        ):
            raise LifecycleError("checkpoint correction history is not monotonic")


def write_checkpoint(
    *,
    repo_path: str,
    state_dir: str,
    assignment: str,
    phase: str,
    expected_branch: str | None = None,
    correction_iteration: int | None = None,
    pr_number: int | None = None,
    pr_head_sha: str | None = None,
    merge_sha: str | None = None,
) -> dict[str, Any]:
    if not isinstance(phase, str) or phase not in _PHASE_RANK:
        raise LifecycleError("phase is outside the stable checkpoint vocabulary")
    safe_assignment = _safe_name(assignment, "assignment")
    repo, state, branch, head, clean = _repo_and_state(repo_path, state_dir)
    if expected_branch is not None and branch != expected_branch:
        raise LifecycleError(f"current branch {branch!r} does not match {expected_branch!r}")
    path = _checkpoint_path(state, safe_assignment, create=False)
    previous: dict[str, Any] | None = None
    if path.exists():
        previous = _load_checkpoint(path)
        if previous.get("assignment") != safe_assignment or previous.get("branch") != branch:
            raise LifecycleError("checkpoint assignment or branch identity changed")
        if Path(previous["repo_path"]).resolve() != repo:
            raise LifecycleError("checkpoint repository identity changed")

    now = _utc_now()
    new_rank = _PHASE_RANK[phase]
    if previous is None:
        iteration = 0 if correction_iteration is None else correction_iteration
        if iteration != 0:
            raise LifecycleError("first checkpoint must start at correction iteration 0")
        history: list[dict[str, Any]] = []
        corrections: list[dict[str, Any]] = []
        highest = phase
        old_phase = None
        old_iteration = 0
        old_head = None
        previous_pr_number = None
        previous_pr_head = None
    else:
        old_phase = previous["phase"]
        old_iteration = previous["correction_iteration"]
        old_head = previous["head"]
        iteration = old_iteration if correction_iteration is None else correction_iteration
        if not isinstance(iteration, int) or isinstance(iteration, bool) or iteration < 0:
            raise LifecycleError("correction iteration must be a non-negative integer")
        if iteration < old_iteration or iteration > old_iteration + 1:
            raise LifecycleError("correction iteration must stay the same or advance by exactly one")
        if old_phase == "merged" and phase != "merged":
            raise LifecycleError("merged is terminal and cannot regress")
        regression = new_rank < _PHASE_RANK[old_phase]
        if regression and iteration != old_iteration + 1:
            raise LifecycleError("phase regression requires an explicit new correction iteration")
        if head != old_head and new_rank <= _PHASE_RANK[old_phase] and iteration == old_iteration:
            if not (old_phase == "implementation_ready" and phase == "implementation_ready"):
                raise LifecycleError("a new HEAD requires phase advancement or a correction iteration")
        history = list(previous["phase_history"])
        corrections = list(previous.get("correction_history", []))
        highest = previous["highest_phase"]
        if iteration == old_iteration + 1:
            corrections.append(
                {
                    "iteration": iteration,
                    "started_at": now,
                    "from_phase": old_phase,
                    "phase": phase,
                    "head": head,
                }
            )
        if new_rank > _PHASE_RANK[highest]:
            highest = phase
        previous_pr_number = previous.get("pr_number")
        previous_pr_head = previous.get("pr_head_sha")

    current_pr_number = pr_number if pr_number is not None else previous_pr_number
    current_pr_head = pr_head_sha if pr_head_sha is not None else previous_pr_head
    current_merge_sha = merge_sha
    if current_pr_number is not None and (
        not isinstance(current_pr_number, int) or isinstance(current_pr_number, bool) or current_pr_number <= 0
    ):
        raise LifecycleError("PR number must be a positive integer")
    if current_pr_head is not None and not _valid_sha(current_pr_head):
        raise LifecycleError("PR head SHA is invalid")
    if _PHASE_RANK[phase] >= _PHASE_RANK["pr_open"]:
        if current_pr_number is None or current_pr_head is None:
            raise LifecycleError("pr_open and later phases require PR number and head SHA")
        if current_pr_head != head:
            raise LifecycleError("PR head SHA must match the current Git HEAD")
    if phase == "merged":
        if not _valid_sha(current_merge_sha):
            raise LifecycleError("merged phase requires a merge SHA")
    elif current_merge_sha is not None:
        raise LifecycleError("merge SHA is only valid at the merged phase")

    event: dict[str, Any] = {
        "phase": phase,
        "correction_iteration": iteration,
        "head": head,
        "timestamp": now,
    }
    if current_pr_number is not None:
        event["pr_number"] = current_pr_number
    if current_pr_head is not None:
        event["pr_head_sha"] = current_pr_head
    if current_merge_sha is not None:
        event["merge_sha"] = current_merge_sha
    history.append(event)

    checkpoint: dict[str, Any] = {
        "schema_version": 1,
        "assignment": safe_assignment,
        "branch": branch,
        "repo_path": str(repo),
        "head": head,
        "worktree_clean": clean,
        "phase": phase,
        "highest_phase": highest,
        "correction_iteration": iteration,
        "phase_history": history,
        "correction_history": corrections,
        "updated_at": now,
    }
    if current_pr_number is not None:
        checkpoint["pr_number"] = current_pr_number
    if current_pr_head is not None:
        checkpoint["pr_head_sha"] = current_pr_head
    if current_merge_sha is not None:
        checkpoint["merge_sha"] = current_merge_sha

    path = _checkpoint_path(state, safe_assignment, create=True)
    _atomic_json(path, checkpoint)
    return {"status": "recorded", "checkpoint_path": str(path), "checkpoint": checkpoint}


def checkpoint_status(*, repo_path: str, state_dir: str, assignment: str) -> dict[str, Any]:
    try:
        safe_assignment = _safe_name(assignment, "assignment")
        repo, state, branch, head, clean = _repo_and_state(repo_path, state_dir)
        path = _checkpoint_path(state, safe_assignment, create=False)
        if not path.exists():
            return {"status": "missing", "assignment": safe_assignment, "repository": str(repo)}
        checkpoint = _load_checkpoint(path)
        if checkpoint.get("assignment") != safe_assignment or Path(checkpoint["repo_path"]).resolve() != repo:
            return {"status": "invalid", "assignment": safe_assignment, "error": "checkpoint identity mismatch"}
        current = checkpoint.get("branch") == branch and checkpoint.get("head") == head
        return {
            "status": "current" if current else "stale",
            "assignment": safe_assignment,
            "branch": branch,
            "head": head,
            "worktree_clean": clean,
            "checkpoint": checkpoint,
        }
    except LifecycleError as exc:
        return {"status": "invalid", "assignment": assignment, "error": str(exc)}


_BATCH_EVENTS = ("preflight", "seed", "task", "review", "final_local", "pr", "ci", "merge")
_BATCH_EVENT_RANK = {event: index for index, event in enumerate(_BATCH_EVENTS)}


def _batch_manifest(repo: Path, control_sha: str, manifest_path: str) -> dict[str, Any]:
    try:
        manifest = parse_manifest(
            _object_blob(repo, control_sha, manifest_path).decode("utf-8")
        )
    except UnicodeError as exc:
        raise LifecycleError("batch manifest is not valid UTF-8") from exc
    if manifest["format"] != "integrated_v8":
        raise LifecycleError("batch checkpoint requires an integrated-v8 manifest")
    return manifest


def _batch_checkpoint_path(state: Path, batch_id: str, *, create: bool) -> Path:
    return _checkpoint_path(state, f"batch-{_safe_name(batch_id, 'batch ID')}", create=create)


def _valid_commit(repo: Path, sha: Any) -> bool:
    return _valid_sha(sha) and _ref_sha(repo, sha) == sha


def _is_ancestor(repo: Path, ancestor: str, descendant: str) -> bool:
    return (
        _git_raw(repo, "merge-base", "--is-ancestor", ancestor, descendant).returncode == 0
    )


def _validate_batch_checkpoint(checkpoint: dict[str, Any], repo: Path) -> None:
    required = {
        "schema_version",
        "mode",
        "batch_id",
        "control_sha",
        "start_main_sha",
        "manifest_path",
        "branch",
        "preflight_branch",
        "repo_path",
        "head",
        "highest_event",
        "preflight_ok",
        "seed_sha",
        "task_order",
        "task_checkpoints",
        "event_history",
        "review_head",
        "final_local_head",
        "updated_at",
    }
    if not required.issubset(checkpoint):
        raise LifecycleError("batch checkpoint is missing required fields")
    schema_version = checkpoint.get("schema_version")
    if (
        not isinstance(schema_version, int)
        or isinstance(schema_version, bool)
        or schema_version != 1
        or checkpoint.get("mode") != "batch"
    ):
        raise LifecycleError("batch checkpoint schema is invalid")
    batch_id = checkpoint.get("batch_id")
    if not isinstance(batch_id, str):
        raise LifecycleError("batch checkpoint batch ID is invalid")
    _safe_name(batch_id, "batch ID")
    if not _valid_commit(repo, checkpoint.get("control_sha")) or not _valid_commit(
        repo, checkpoint.get("start_main_sha")
    ):
        raise LifecycleError("batch checkpoint control/start identity is invalid")
    if not isinstance(checkpoint.get("manifest_path"), str):
        raise LifecycleError("batch checkpoint manifest path is invalid")
    _safe_relative_path(checkpoint["manifest_path"], "manifest path")
    if not isinstance(checkpoint.get("branch"), str) or not checkpoint["branch"]:
        raise LifecycleError("batch checkpoint branch is invalid")
    if not isinstance(checkpoint.get("preflight_branch"), str) or not checkpoint[
        "preflight_branch"
    ]:
        raise LifecycleError("batch checkpoint preflight branch is invalid")
    if not isinstance(checkpoint.get("repo_path"), str) or not checkpoint["repo_path"]:
        raise LifecycleError("batch checkpoint repository is invalid")
    if not _valid_commit(repo, checkpoint.get("head")):
        raise LifecycleError("batch checkpoint HEAD is not a valid commit")
    highest = checkpoint.get("highest_event")
    if not isinstance(highest, str) or highest not in _BATCH_EVENT_RANK:
        raise LifecycleError("batch checkpoint high-water event is invalid")
    if checkpoint.get("preflight_ok") is not True:
        raise LifecycleError("batch checkpoint does not record successful preflight")
    seed = checkpoint.get("seed_sha")
    if seed is not None:
        if not _valid_commit(repo, seed):
            raise LifecycleError("batch checkpoint seed is not a valid commit")
        parent = _git(repo, "rev-parse", f"{seed}^")
        if parent != checkpoint["start_main_sha"]:
            raise LifecycleError("batch checkpoint seed has the wrong parent")
    task_order = checkpoint.get("task_order")
    task_checkpoints = checkpoint.get("task_checkpoints")
    if (
        not isinstance(task_order, list)
        or not task_order
        or any(not isinstance(task_id, str) for task_id in task_order)
        or len(task_order) != len(set(task_order))
        or not isinstance(task_checkpoints, list)
    ):
        raise LifecycleError("batch checkpoint task order is invalid")
    completed_ids: list[str] = []
    for item in task_checkpoints:
        if not isinstance(item, dict):
            raise LifecycleError("batch task checkpoint is invalid")
        task_id = item.get("id")
        head = item.get("head")
        correction_count = item.get("correction_count")
        if (
            not isinstance(task_id, str)
            or not _valid_commit(repo, head)
            or not isinstance(correction_count, int)
            or isinstance(correction_count, bool)
            or correction_count < 0
            or seed is None
            or not _is_ancestor(repo, seed, head)
        ):
            raise LifecycleError("batch task checkpoint fact is invalid")
        completed_ids.append(task_id)
    if completed_ids != task_order[: len(completed_ids)]:
        raise LifecycleError("batch task checkpoints skip, duplicate, or reorder tasks")
    history = checkpoint.get("event_history")
    if not isinstance(history, list) or not history:
        raise LifecycleError("batch checkpoint event history is invalid")
    history_tasks: list[dict[str, Any]] = []
    maximum_rank = -1
    for index, item in enumerate(history):
        if (
            not isinstance(item, dict)
            or not isinstance(item.get("event"), str)
            or item.get("event") not in _BATCH_EVENT_RANK
        ):
            raise LifecycleError("batch checkpoint history contains an invalid event")
        if not _valid_commit(repo, item.get("head")) or not _valid_timestamp(
            item.get("timestamp")
        ):
            raise LifecycleError("batch checkpoint history contains an invalid fact")
        event = item["event"]
        if index == 0 and event != "preflight":
            raise LifecycleError("batch checkpoint history must begin with preflight")
        if index > 0 and history[index - 1]["event"] == "merge":
            raise LifecycleError("batch checkpoint history advances after merge")
        maximum_rank = max(maximum_rank, _BATCH_EVENT_RANK[event])
        if event == "task":
            history_task_id = item.get("task_id")
            history_correction = item.get("correction_count")
            next_id = task_order[len(history_tasks)] if len(history_tasks) < len(task_order) else None
            if history_task_id == next_id and history_correction == 0:
                history_tasks.append(
                    {
                        "id": history_task_id,
                        "head": item["head"],
                        "correction_count": 0,
                    }
                )
            elif history_tasks and history_task_id == history_tasks[-1]["id"]:
                if history_correction != history_tasks[-1]["correction_count"] + 1:
                    raise LifecycleError("batch checkpoint correction history regresses")
                history_tasks[-1] = {
                    "id": history_task_id,
                    "head": item["head"],
                    "correction_count": history_correction,
                }
            else:
                raise LifecycleError("batch checkpoint history reorders task checkpoints")
    if _BATCH_EVENT_RANK[highest] != maximum_rank:
        raise LifecycleError("batch checkpoint high-water event does not match history")
    if history_tasks != task_checkpoints:
        raise LifecycleError("batch checkpoint tasks do not match event history")
    review_head = checkpoint.get("review_head")
    final_local_head = checkpoint.get("final_local_head")
    for label, value in (("review", review_head), ("final local", final_local_head)):
        if value is not None and (
            not _valid_commit(repo, value)
            or seed is None
            or not _is_ancestor(repo, seed, value)
        ):
            raise LifecycleError(f"batch checkpoint {label} head is invalid")
    if review_head is not None and len(task_checkpoints) != len(task_order):
        raise LifecycleError("batch review was recorded before all task checkpoints")
    if final_local_head is not None and review_head is None:
        raise LifecycleError("batch final-local state requires review")
    pr_number = checkpoint.get("pr_number")
    pr_head = checkpoint.get("pr_head_sha")
    if (pr_number is None) != (pr_head is None):
        raise LifecycleError("batch PR number/head must be recorded together")
    if pr_number is not None:
        if (
            not isinstance(pr_number, int)
            or isinstance(pr_number, bool)
            or pr_number <= 0
            or not _valid_commit(repo, pr_head)
            or final_local_head is None
            or pr_head != final_local_head
        ):
            raise LifecycleError("batch PR facts are inconsistent")
    ci_head = checkpoint.get("ci_green_head")
    if ci_head is not None and (pr_head is None or ci_head != pr_head):
        raise LifecycleError("batch CI-green head does not match the exact PR head")
    merge_sha = checkpoint.get("merge_sha")
    if merge_sha is not None and (
        ci_head is None
        or not _valid_commit(repo, merge_sha)
        or not _is_ancestor(repo, ci_head, merge_sha)
    ):
        raise LifecycleError("batch merge facts are inconsistent with green CI")
    if not _valid_timestamp(checkpoint.get("updated_at")):
        raise LifecycleError("batch checkpoint timestamp is invalid")


def write_batch_checkpoint(
    *,
    repo_path: str,
    state_dir: str,
    control_sha: str,
    manifest_path: str,
    event: str,
    seed_sha: str | None = None,
    task_id: str | None = None,
    correction_count: int | None = None,
    pr_number: int | None = None,
    pr_head_sha: str | None = None,
    ci_head_sha: str | None = None,
    merge_sha: str | None = None,
) -> dict[str, Any]:
    if event not in _BATCH_EVENT_RANK:
        raise LifecycleError("batch checkpoint event is invalid")
    repo, state, current_branch, head, clean = _repo_and_state(repo_path, state_dir)
    if not clean:
        raise LifecycleError("batch checkpoint requires a clean worktree")
    manifest = _batch_manifest(repo, control_sha, manifest_path)
    path = _batch_checkpoint_path(state, manifest["batch_id"], create=False)
    previous: dict[str, Any] | None = None
    if path.exists():
        previous = _load_batch_checkpoint(path, repo)
        identity = (
            previous["control_sha"] == control_sha
            and previous["start_main_sha"] == manifest["expected_start_main_sha"]
            and previous["manifest_path"] == _safe_relative_path(manifest_path, "manifest path")
            and previous["branch"] == manifest["implementation_branch"]
            and Path(previous["repo_path"]).resolve() == repo
            and previous["task_order"] == [task["id"] for task in manifest["tasks"]]
        )
        if not identity:
            raise LifecycleError("batch checkpoint identity changed")
    elif event != "preflight":
        raise LifecycleError("batch checkpoint must begin with preflight")

    if previous is None:
        if head != manifest["expected_start_main_sha"]:
            raise LifecycleError("batch preflight HEAD must be the expected start-main")
        payload: dict[str, Any] = {
            "schema_version": 1,
            "mode": "batch",
            "batch_id": manifest["batch_id"],
            "control_sha": control_sha,
            "start_main_sha": manifest["expected_start_main_sha"],
            "manifest_path": _safe_relative_path(manifest_path, "manifest path"),
            "branch": manifest["implementation_branch"],
            "preflight_branch": current_branch,
            "repo_path": str(repo),
            "head": head,
            "highest_event": "preflight",
            "preflight_ok": True,
            "seed_sha": None,
            "task_order": [task["id"] for task in manifest["tasks"]],
            "task_checkpoints": [],
            "event_history": [
                {"event": "preflight", "head": head, "timestamp": _utc_now()}
            ],
            "review_head": None,
            "final_local_head": None,
            "updated_at": _utc_now(),
        }
    else:
        if event == "preflight":
            raise LifecycleError("batch preflight cannot be recorded twice")
        if previous.get("merge_sha") is not None:
            raise LifecycleError("batch merge is terminal")
        if event != "merge" and current_branch != manifest["implementation_branch"]:
            raise LifecycleError("batch lifecycle event requires the implementation branch")
        payload = dict(previous)
        payload["head"] = head
        payload["updated_at"] = _utc_now()
        if _BATCH_EVENT_RANK[event] > _BATCH_EVENT_RANK[payload["highest_event"]]:
            payload["highest_event"] = event

        if event == "seed":
            if previous["seed_sha"] is not None or current_branch != manifest["implementation_branch"]:
                raise LifecycleError("batch seed can only be recorded once on its implementation branch")
            selected_seed = seed_sha or head
            verification = verify_batch_seed(
                repo_path=str(repo),
                control_sha=control_sha,
                manifest_path=manifest_path,
                seed_sha=selected_seed,
                allow_later_head=selected_seed != head,
            )
            if not verification["ok"]:
                raise LifecycleError("batch seed verification failed")
            payload["seed_sha"] = selected_seed
        elif event == "task":
            if previous["seed_sha"] is None or current_branch != manifest["implementation_branch"]:
                raise LifecycleError("batch task checkpoint requires its seed and implementation branch")
            if not _is_ancestor(repo, previous["seed_sha"], head):
                raise LifecycleError("batch task HEAD does not preserve seed ancestry")
            completed = [dict(item) for item in previous["task_checkpoints"]]
            next_id = previous["task_order"][len(completed)] if len(completed) < len(previous["task_order"]) else None
            requested_correction = 0 if correction_count is None else correction_count
            if task_id == next_id and requested_correction == 0:
                completed.append({"id": task_id, "head": head, "correction_count": 0})
            elif completed and task_id == completed[-1]["id"]:
                expected_correction = completed[-1]["correction_count"] + 1
                if requested_correction != expected_correction or head == completed[-1]["head"]:
                    raise LifecycleError("batch task correction must advance count and HEAD exactly once")
                completed[-1] = {
                    "id": task_id,
                    "head": head,
                    "correction_count": requested_correction,
                }
                for key in (
                    "review_head",
                    "final_local_head",
                    "pr_number",
                    "pr_head_sha",
                    "ci_green_head",
                    "merge_sha",
                ):
                    payload.pop(key, None)
                payload["review_head"] = None
                payload["final_local_head"] = None
            else:
                raise LifecycleError("batch task checkpoints must advance in manifest order")
            payload["task_checkpoints"] = completed
        elif event == "review":
            if len(previous["task_checkpoints"]) != len(previous["task_order"]):
                raise LifecycleError("batch review requires every ordered task checkpoint")
            if previous.get("review_head") is not None:
                raise LifecycleError("batch review is already recorded")
            payload["review_head"] = head
        elif event == "final_local":
            if previous.get("review_head") is None:
                raise LifecycleError("batch final-local verification requires review")
            if previous.get("final_local_head") is not None:
                raise LifecycleError("batch final-local verification is already recorded")
            payload["final_local_head"] = head
        elif event == "pr":
            if previous.get("final_local_head") != head:
                raise LifecycleError("batch PR head must equal the final-local verified head")
            if previous.get("pr_number") is not None:
                raise LifecycleError("batch PR is already recorded for this exact head")
            if not isinstance(pr_number, int) or isinstance(pr_number, bool) or pr_number <= 0:
                raise LifecycleError("batch PR number must be positive")
            selected_pr_head = pr_head_sha or head
            if selected_pr_head != head:
                raise LifecycleError("batch PR head must equal current HEAD")
            if previous.get("pr_number") not in {None, pr_number}:
                raise LifecycleError("batch PR number cannot change")
            payload["pr_number"] = pr_number
            payload["pr_head_sha"] = selected_pr_head
            payload.pop("ci_green_head", None)
            payload.pop("merge_sha", None)
        elif event == "ci":
            selected_ci_head = ci_head_sha or head
            if previous.get("ci_green_head") is not None:
                raise LifecycleError("batch exact-head CI is already recorded")
            if previous.get("pr_head_sha") != selected_ci_head or head != selected_ci_head:
                raise LifecycleError("batch CI must be green for the exact current PR head")
            payload["ci_green_head"] = selected_ci_head
        elif event == "merge":
            selected_merge = merge_sha or head
            if previous.get("ci_green_head") != previous.get("pr_head_sha"):
                raise LifecycleError("batch merge requires green CI for the exact PR head")
            if selected_merge != head or not _is_ancestor(repo, previous["ci_green_head"], selected_merge):
                raise LifecycleError("batch merge commit must contain the green PR head")
            payload["merge_sha"] = selected_merge

        history_event: dict[str, Any] = {
            "event": event,
            "head": head,
            "timestamp": payload["updated_at"],
        }
        if event == "task":
            history_event["task_id"] = task_id
            history_event["correction_count"] = 0 if correction_count is None else correction_count
        payload["event_history"] = [*previous["event_history"], history_event]

    _validate_batch_checkpoint(payload, repo)
    path = _batch_checkpoint_path(state, manifest["batch_id"], create=True)
    _atomic_json(path, payload)
    return {"status": "recorded", "checkpoint_path": str(path), "checkpoint": payload}


def _load_batch_checkpoint(path: Path, repo: Path) -> dict[str, Any]:
    if path.is_symlink():
        raise LifecycleError("batch checkpoint file must not be a symlink")
    try:
        with path.open("r", encoding="utf-8") as stream:
            checkpoint = json.load(stream)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise LifecycleError("batch checkpoint JSON is missing or malformed") from exc
    if not isinstance(checkpoint, dict):
        raise LifecycleError("batch checkpoint JSON must be an object")
    _validate_batch_checkpoint(checkpoint, repo)
    return checkpoint


def batch_checkpoint_status(
    *,
    repo_path: str,
    state_dir: str,
    control_sha: str,
    manifest_path: str,
) -> dict[str, Any]:
    try:
        repo, state, branch, head, clean = _repo_and_state(repo_path, state_dir)
        manifest = _batch_manifest(repo, control_sha, manifest_path)
        path = _batch_checkpoint_path(state, manifest["batch_id"], create=False)
        if not path.exists():
            return {"status": "missing", "batch_id": manifest["batch_id"]}
        checkpoint = _load_batch_checkpoint(path, repo)
        identity = (
            checkpoint["control_sha"] == control_sha
            and checkpoint["manifest_path"] == _safe_relative_path(manifest_path, "manifest path")
            and checkpoint["task_order"] == [task["id"] for task in manifest["tasks"]]
            and Path(checkpoint["repo_path"]).resolve() == repo
        )
        if not identity:
            raise LifecycleError("batch checkpoint identity mismatch")
        expected_head = checkpoint.get("merge_sha") or checkpoint["head"]
        expected_branch = (
            "main"
            if checkpoint.get("merge_sha")
            else checkpoint["branch"]
            if checkpoint.get("seed_sha")
            else checkpoint["preflight_branch"]
        )
        current = head == expected_head and branch == expected_branch
        return {
            "status": "current" if current else "stale",
            "batch_id": manifest["batch_id"],
            "branch": branch,
            "head": head,
            "worktree_clean": clean,
            "checkpoint": checkpoint,
        }
    except LifecycleError as exc:
        return {"status": "invalid", "error": str(exc)}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    preflight = commands.add_parser("preflight", help="check local batch/assignment prerequisites")
    preflight.add_argument("--repo", required=True)
    preflight.add_argument("--expected-repo-path")
    preflight.add_argument("--expected-origin")
    preflight.add_argument("--expected-branch", default="main")
    preflight.add_argument("--expected-start-main-sha")
    preflight.add_argument("--remote", default="origin")
    preflight.add_argument("--control-branch", required=True)
    preflight.add_argument("--control-sha", required=True)
    preflight.add_argument("--manifest", required=True)
    preflight.add_argument("--task", required=True)
    preflight.add_argument("--expected-task-order")
    preflight.add_argument("--expected-task-spec-source")
    preflight.add_argument("--expected-assignment-destination")
    preflight.add_argument("--allow-existing-task-branch", action="store_true")

    seed = commands.add_parser("verify-seed", help="verify an immutable task seed")
    seed.add_argument("--repo", required=True)
    seed.add_argument("--branch", required=True)
    seed.add_argument("--base-sha", required=True)
    seed.add_argument("--control-sha", required=True)
    seed.add_argument("--assignment-source", required=True)
    seed.add_argument("--assignment-destination", required=True)
    seed.add_argument("--seed-sha")
    seed.add_argument("--allow-later-head", action="store_true")

    batch_seed = commands.add_parser(
        "verify-batch-seed", help="verify one immutable integrated-batch seed"
    )
    batch_seed.add_argument("--repo", required=True)
    batch_seed.add_argument("--control-sha", required=True)
    batch_seed.add_argument("--manifest", required=True)
    batch_seed.add_argument("--seed-sha")
    batch_seed.add_argument("--allow-later-head", action="store_true")

    checkpoint = commands.add_parser("checkpoint", help="write one durable lifecycle checkpoint")
    checkpoint.add_argument("--repo", required=True)
    checkpoint.add_argument("--state-dir", required=True)
    checkpoint.add_argument("--assignment", required=True)
    checkpoint.add_argument("--phase", choices=PHASES, required=True)
    checkpoint.add_argument("--expected-branch")
    checkpoint.add_argument("--correction-iteration", type=int)
    checkpoint.add_argument("--pr-number", type=int)
    checkpoint.add_argument("--pr-head-sha")
    checkpoint.add_argument("--merge-sha")

    status = commands.add_parser("checkpoint-status", help="inspect a checkpoint against current Git state")
    status.add_argument("--repo", required=True)
    status.add_argument("--state-dir", required=True)
    status.add_argument("--assignment", required=True)

    batch_checkpoint = commands.add_parser(
        "batch-checkpoint", help="record one integrated-batch lifecycle event"
    )
    batch_checkpoint.add_argument("--repo", required=True)
    batch_checkpoint.add_argument("--state-dir", required=True)
    batch_checkpoint.add_argument("--control-sha", required=True)
    batch_checkpoint.add_argument("--manifest", required=True)
    batch_checkpoint.add_argument("--event", choices=_BATCH_EVENTS, required=True)
    batch_checkpoint.add_argument("--seed-sha")
    batch_checkpoint.add_argument("--task")
    batch_checkpoint.add_argument("--correction-count", type=int)
    batch_checkpoint.add_argument("--pr-number", type=int)
    batch_checkpoint.add_argument("--pr-head-sha")
    batch_checkpoint.add_argument("--ci-head-sha")
    batch_checkpoint.add_argument("--merge-sha")

    batch_status = commands.add_parser(
        "batch-checkpoint-status", help="inspect integrated-batch lifecycle state"
    )
    batch_status.add_argument("--repo", required=True)
    batch_status.add_argument("--state-dir", required=True)
    batch_status.add_argument("--control-sha", required=True)
    batch_status.add_argument("--manifest", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "preflight":
            expected_order = (
                [part.strip() for part in args.expected_task_order.split(",") if part.strip()]
                if args.expected_task_order is not None
                else None
            )
            result = check_preflight(
                repo_path=args.repo,
                expected_repo_path=args.expected_repo_path,
                expected_origin=args.expected_origin,
                expected_branch=args.expected_branch,
                expected_start_main_sha=args.expected_start_main_sha,
                remote=args.remote,
                control_branch=args.control_branch,
                control_sha=args.control_sha,
                manifest_path=args.manifest,
                task_id=args.task,
                expected_task_order=expected_order,
                expected_task_spec_source=args.expected_task_spec_source,
                expected_assignment_destination=args.expected_assignment_destination,
                allow_existing_task_branch=args.allow_existing_task_branch,
            )
        elif args.command == "verify-seed":
            result = verify_seed(
                repo_path=args.repo,
                branch=args.branch,
                base_sha=args.base_sha,
                control_sha=args.control_sha,
                assignment_source=args.assignment_source,
                assignment_destination=args.assignment_destination,
                seed_sha=args.seed_sha,
                allow_later_head=args.allow_later_head,
            )
        elif args.command == "verify-batch-seed":
            result = verify_batch_seed(
                repo_path=args.repo,
                control_sha=args.control_sha,
                manifest_path=args.manifest,
                seed_sha=args.seed_sha,
                allow_later_head=args.allow_later_head,
            )
        elif args.command == "checkpoint":
            result = write_checkpoint(
                repo_path=args.repo,
                state_dir=args.state_dir,
                assignment=args.assignment,
                phase=args.phase,
                expected_branch=args.expected_branch,
                correction_iteration=args.correction_iteration,
                pr_number=args.pr_number,
                pr_head_sha=args.pr_head_sha,
                merge_sha=args.merge_sha,
            )
        elif args.command == "checkpoint-status":
            result = checkpoint_status(
                repo_path=args.repo,
                state_dir=args.state_dir,
                assignment=args.assignment,
            )
        elif args.command == "batch-checkpoint":
            result = write_batch_checkpoint(
                repo_path=args.repo,
                state_dir=args.state_dir,
                control_sha=args.control_sha,
                manifest_path=args.manifest,
                event=args.event,
                seed_sha=args.seed_sha,
                task_id=args.task,
                correction_count=args.correction_count,
                pr_number=args.pr_number,
                pr_head_sha=args.pr_head_sha,
                ci_head_sha=args.ci_head_sha,
                merge_sha=args.merge_sha,
            )
        else:
            result = batch_checkpoint_status(
                repo_path=args.repo,
                state_dir=args.state_dir,
                control_sha=args.control_sha,
                manifest_path=args.manifest,
            )
    except LifecycleError as exc:
        result = {"status": "invalid", "ok": False, "error": str(exc)}

    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result.get("status") in {"ok", "verified", "recorded", "current"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
