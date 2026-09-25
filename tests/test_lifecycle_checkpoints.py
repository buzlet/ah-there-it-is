from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from tools.agent import lifecycle_checkpoints as lifecycle


CONTROL_BRANCH = "queue/post-test-control"
TASK_BRANCH = "feat/agent-test"
REMOTE_URL = "https://example.invalid/buzlet/ah-there-it-is.git"
MANIFEST_PATH = "agent-tasks/batches/test/manifest.md"
SPEC_PATH = "agent-tasks/batches/test/0031-task.md"
ASSIGNMENT_PATH = "agent-tasks/assignments/0031-task.md"
MANIFEST = f"""# Test batch

Batch ID: `test-batch`

### 0030 — earlier task

Branch: `feat/agent-earlier`
Spec source: `agent-tasks/batches/test/0030-task.md`
Assignment destination: `agent-tasks/assignments/0030-task.md`

### 0031 — current task

Branch: `{TASK_BRANCH}`
Spec source: `{SPEC_PATH}`
Assignment destination: `{ASSIGNMENT_PATH}`
Depends on: 0030 merged.
"""
SPEC = "# Exact issued task\n\nPreserve these bytes.\n"


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return result.stdout.strip()


def _commit(repo: Path, message: str) -> str:
    _git(repo, "add", "--all")
    _git(repo, "commit", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


def _configure(repo: Path) -> None:
    _git(repo, "config", "user.name", "Lifecycle Test")
    _git(repo, "config", "user.email", "lifecycle@example.invalid")


def _batch_repo(tmp_path: Path) -> dict[str, str | Path]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "--initial-branch=main")
    _configure(repo)
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    base = _commit(repo, "base")
    _git(repo, "remote", "add", "origin", REMOTE_URL)
    _git(repo, "update-ref", "refs/remotes/origin/main", base)

    _git(repo, "checkout", "-b", CONTROL_BRANCH)
    (repo / "agent-tasks/batches/test").mkdir(parents=True)
    (repo / "agent-tasks/assignments").mkdir(parents=True)
    (repo / MANIFEST_PATH).write_text(MANIFEST, encoding="utf-8")
    (repo / SPEC_PATH).write_bytes(SPEC.encode())
    (repo / "agent-tasks/batches/test/0030-task.md").write_text("earlier\n", encoding="utf-8")
    control = _commit(repo, "control manifest")
    _git(repo, "update-ref", f"refs/remotes/origin/{CONTROL_BRANCH}", control)
    _git(repo, "checkout", "main")
    return {
        "repo": repo,
        "base": base,
        "control": control,
        "manifest": MANIFEST_PATH,
        "spec": SPEC_PATH,
        "assignment": ASSIGNMENT_PATH,
    }


def _integrated_manifest(base: str, *, destinations: list[str] | None = None) -> str:
    task_ids = [f"{number:04d}" for number in range(51, 61)]
    specs = [f"agent-tasks/batches/integrated/{task_id}-task.md" for task_id in task_ids]
    assignments = destinations or [
        f"agent-tasks/assignments/{task_id}-task.md" for task_id in task_ids
    ]
    ordered = "\n".join(
        f"{position}. {task_id} — task {task_id}"
        for position, task_id in enumerate(task_ids, start=1)
    )
    spec_lines = "\n".join(f"- `{path}`" for path in specs)
    assignment_lines = "\n".join(f"- `{path}`" for path in assignments)
    return f"""# Integrated batch

Batch ID: `integrated-test`

Expected start main:

`{base}`

Implementation branch:

`{TASK_BRANCH}`

Execution user:

`runner`

Required work directory:

`/canonical/checkout`

Batch review destination:

`agent-tasks/reviews/integrated-r1.md`

Full local regression:

`full_local_required: true`

## Ordered tasks

{ordered}

Exact task specs:
{spec_lines}

Seed destinations:
{assignment_lines}
"""


def _integrated_batch_repo(tmp_path: Path) -> dict[str, str | Path]:
    repo = tmp_path / "integrated-repo"
    repo.mkdir()
    _git(repo, "init", "--initial-branch=main")
    _configure(repo)
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    base = _commit(repo, "base")
    _git(repo, "remote", "add", "origin", REMOTE_URL)
    _git(repo, "update-ref", "refs/remotes/origin/main", base)
    _git(repo, "checkout", "-b", CONTROL_BRANCH)
    manifest_path = "agent-tasks/batches/integrated/manifest.md"
    manifest = _integrated_manifest(base)
    (repo / manifest_path).parent.mkdir(parents=True)
    (repo / manifest_path).write_text(manifest, encoding="utf-8")
    for task_id in (f"{number:04d}" for number in range(51, 61)):
        (repo / f"agent-tasks/batches/integrated/{task_id}-task.md").write_text(
            f"# Task {task_id}\n", encoding="utf-8"
        )
    control = _commit(repo, "integrated control manifest")
    _git(repo, "update-ref", f"refs/remotes/origin/{CONTROL_BRANCH}", control)
    _git(repo, "checkout", "main")
    return {
        "repo": repo,
        "base": base,
        "control": control,
        "manifest": manifest_path,
        "spec": "agent-tasks/batches/integrated/0055-task.md",
        "assignment": "agent-tasks/assignments/0055-task.md",
    }


def _integrated_preflight(repo: dict[str, str | Path], **overrides):
    values = {
        "repo_path": str(repo["repo"]),
        "expected_repo_path": str(repo["repo"]),
        "expected_origin": REMOTE_URL,
        "control_branch": CONTROL_BRANCH,
        "control_sha": str(repo["control"]),
        "manifest_path": str(repo["manifest"]),
        "task_id": "0055",
        "expected_start_main_sha": str(repo["base"]),
        "expected_task_order": [f"{number:04d}" for number in range(51, 61)],
        "expected_task_spec_source": str(repo["spec"]),
        "expected_assignment_destination": str(repo["assignment"]),
    }
    values.update(overrides)
    return lifecycle.check_preflight(**values)


def _git_blob(repo: Path, revision: str, path: str) -> bytes:
    return subprocess.run(
        ["git", "-C", str(repo), "cat-file", "blob", f"{revision}:{path}"],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    ).stdout


def _integrated_seed(
    repo: dict[str, str | Path], *, omit_task: str | None = None
) -> str:
    path = Path(repo["repo"])
    _git(path, "checkout", "-b", TASK_BRANCH, str(repo["base"]))
    manifest_path = str(repo["manifest"])
    destination = path / manifest_path
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(_git_blob(path, str(repo["control"]), manifest_path))
    for task_id in (f"{number:04d}" for number in range(51, 61)):
        if task_id == omit_task:
            continue
        source = f"agent-tasks/batches/integrated/{task_id}-task.md"
        assignment = path / f"agent-tasks/assignments/{task_id}-task.md"
        assignment.parent.mkdir(parents=True, exist_ok=True)
        assignment.write_bytes(_git_blob(path, str(repo["control"]), source))
    return _commit(path, "integrated batch seed")


def _batch_checkpoint_args(
    repo: dict[str, str | Path], state: Path, event: str, **overrides
):
    values = {
        "repo_path": str(repo["repo"]),
        "state_dir": str(state),
        "control_sha": str(repo["control"]),
        "manifest_path": str(repo["manifest"]),
        "event": event,
    }
    values.update(overrides)
    return values


def _preflight(repo: dict[str, str | Path], **overrides):
    values = {
        "repo_path": str(repo["repo"]),
        "expected_repo_path": str(repo["repo"]),
        "expected_origin": REMOTE_URL,
        "control_branch": CONTROL_BRANCH,
        "control_sha": str(repo["control"]),
        "manifest_path": str(repo["manifest"]),
        "task_id": "0031",
        "expected_start_main_sha": str(repo["base"]),
        "expected_task_order": ["0030", "0031"],
        "expected_task_spec_source": str(repo["spec"]),
        "expected_assignment_destination": str(repo["assignment"]),
    }
    values.update(overrides)
    return lifecycle.check_preflight(**values)


def _task_branch(repo: Path, base: str, assignment: str = SPEC) -> tuple[str, str]:
    _git(repo, "checkout", "-b", TASK_BRANCH, base)
    destination = repo / ASSIGNMENT_PATH
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(assignment.encode())
    seed = _commit(repo, "immutable seed")
    return seed, _git(repo, "rev-parse", f"{seed}^")


def _simple_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "checkpoint-repo"
    repo.mkdir()
    _git(repo, "init", "--initial-branch=" + TASK_BRANCH)
    _configure(repo)
    (repo / "README.md").write_text("initial\n", encoding="utf-8")
    _commit(repo, "initial")
    return repo


def test_preflight_checks_manifest_control_identity_and_target_branch(tmp_path: Path) -> None:
    repo = _batch_repo(tmp_path)

    result = _preflight(repo)

    assert result["status"] == "ok"
    assert result["manifest_format"] == "legacy"
    assert result["manifest_mode"] == "per_task"
    assert result["selected_task"] == {
        "position": 2,
        "id": "0031",
        "title": "current task",
        "branch": TASK_BRANCH,
        "spec_source": SPEC_PATH,
        "assignment_destination": ASSIGNMENT_PATH,
        "depends_on": "0030 merged.",
    }
    assert all(check["ok"] for check in result["checks"])


def test_manifest_parses_integrated_batch_metadata_and_shared_branch(tmp_path: Path) -> None:
    repo = _integrated_batch_repo(tmp_path)
    manifest = lifecycle.parse_manifest(
        _git(Path(repo["repo"]), "show", f"{repo['control']}:{repo['manifest']}")
    )

    assert manifest["format"] == "integrated_v8"
    assert manifest["mode"] == "integrated_batch"
    assert manifest["expected_start_main_sha"] == repo["base"]
    assert manifest["implementation_branch"] == TASK_BRANCH
    assert manifest["execution_user"] == "runner"
    assert manifest["workdir"] == "/canonical/checkout"
    assert manifest["review_destination"] == "agent-tasks/reviews/integrated-r1.md"
    assert manifest["full_local_required"] is True
    assert [task["id"] for task in manifest["tasks"]] == [
        f"{number:04d}" for number in range(51, 61)
    ]
    assert {task["branch"] for task in manifest["tasks"]} == {TASK_BRANCH}


def test_preflight_accepts_integrated_manifest_without_binding_declared_workdir(
    tmp_path: Path,
) -> None:
    repo = _integrated_batch_repo(tmp_path)

    result = _integrated_preflight(repo)

    assert result["status"] == "ok"
    assert result["manifest_format"] == "integrated_v8"
    assert result["manifest_mode"] == "integrated_batch"
    assert result["selected_task"]["id"] == "0055"
    assert all(check["ok"] for check in result["checks"])


@pytest.mark.parametrize(
    "manifest, message",
    [
        (
            lambda base: _integrated_manifest(
                base,
                destinations=[
                    "agent-tasks/assignments/0052-task.md",
                    "agent-tasks/assignments/0051-task.md",
                    *[
                        f"agent-tasks/assignments/{number:04d}-task.md"
                        for number in range(53, 61)
                    ],
                ],
            ),
            "align exactly",
        ),
        (
            lambda base: _integrated_manifest(base).replace(
                "agent-tasks/assignments/0052-task.md",
                "agent-tasks/assignments/0051-second.md",
            ),
            "duplicate task paths",
        ),
        (
            lambda base: _integrated_manifest(base).replace(
                "agent-tasks/assignments/0055-task.md", "../0055-task.md"
            ),
            "safe repository-relative path",
        ),
        (
            lambda base: _integrated_manifest(base).replace(base, "not-a-sha"),
            "SHA is invalid",
        ),
        (
            lambda base: _integrated_manifest(base).replace(
                "2. 0052 — task 0052", "3. 0052 — task 0052"
            ),
            "positions are contradictory",
        ),
    ],
)
def test_manifest_rejects_malformed_integrated_alignment(manifest, message) -> None:
    base = "a" * 40
    with pytest.raises(lifecycle.LifecycleError, match=message):
        lifecycle.parse_manifest(manifest(base))


def test_preflight_rejects_integrated_wrong_start_control_and_dirty_checkout(
    tmp_path: Path,
) -> None:
    repo = _integrated_batch_repo(tmp_path)
    path = Path(repo["repo"])

    wrong_start = _integrated_preflight(repo, expected_start_main_sha="1" * 40)
    wrong_control = _integrated_preflight(repo, control_sha=str(repo["base"]))
    (path / "untracked.txt").write_text("dirty\n", encoding="utf-8")
    dirty = _integrated_preflight(repo)

    assert wrong_start["status"] == "blocked"
    assert not next(
        check for check in wrong_start["checks"] if check["name"] == "manifest_start_main"
    )["ok"]
    assert wrong_control["status"] == "blocked"
    assert not next(
        check for check in wrong_control["checks"] if check["name"] == "control_branch_sha"
    )["ok"]
    assert dirty["status"] == "blocked"
    assert not next(
        check for check in dirty["checks"] if check["name"] == "worktree_clean"
    )["ok"]


def test_preflight_rejects_wrong_start_sha_and_wrong_control_sha(tmp_path: Path) -> None:
    repo = _batch_repo(tmp_path)

    wrong_start = _preflight(repo, expected_start_main_sha="1" * 40)
    wrong_control = _preflight(repo, control_sha=str(repo["base"]))

    assert wrong_start["status"] == "blocked"
    assert not next(check for check in wrong_start["checks"] if check["name"] == "expected_start_main")["ok"]
    assert wrong_control["status"] == "blocked"
    assert not next(check for check in wrong_control["checks"] if check["name"] == "manifest_at_control_sha")["ok"]


def test_preflight_rejects_dirty_worktree_and_existing_task_branch(tmp_path: Path) -> None:
    repo = _batch_repo(tmp_path)
    path = Path(repo["repo"])
    (path / "untracked.txt").write_text("dirty\n", encoding="utf-8")

    dirty = _preflight(repo)
    (path / "untracked.txt").unlink()
    _git(path, "branch", TASK_BRANCH, str(repo["base"]))
    existing = _preflight(repo)

    assert dirty["status"] == "blocked"
    assert not next(check for check in dirty["checks"] if check["name"] == "worktree_clean")["ok"]
    assert existing["status"] == "blocked"
    assert not next(check for check in existing["checks"] if check["name"] == "target_task_branch")["ok"]
    assert _preflight(repo, allow_existing_task_branch=True)["status"] == "ok"


def test_seed_verification_checks_exact_assignment_and_later_ancestry(tmp_path: Path) -> None:
    repo = _batch_repo(tmp_path)
    path = Path(repo["repo"])
    seed, base = _task_branch(path, str(repo["base"]))
    args = {
        "repo_path": str(path),
        "branch": TASK_BRANCH,
        "base_sha": base,
        "control_sha": str(repo["control"]),
        "assignment_source": str(repo["spec"]),
        "assignment_destination": str(repo["assignment"]),
    }

    verified = lifecycle.verify_seed(**args)
    assert verified["status"] == "verified"
    assert verified["seed_sha"] == seed

    (path / "implementation.py").write_text("# implementation\n", encoding="utf-8")
    later = _commit(path, "implementation")
    assert lifecycle.verify_seed(**args, seed_sha=seed)["status"] == "blocked"
    later_check = lifecycle.verify_seed(**args, seed_sha=seed, allow_later_head=True)
    assert later_check["status"] == "verified"
    assert later_check["head"] == later


def test_seed_verification_rejects_assignment_byte_mismatch_and_non_ancestor(tmp_path: Path) -> None:
    repo = _batch_repo(tmp_path)
    path = Path(repo["repo"])
    seed, base = _task_branch(path, str(repo["base"]), assignment="different bytes\n")
    args = {
        "repo_path": str(path),
        "branch": TASK_BRANCH,
        "base_sha": base,
        "control_sha": str(repo["control"]),
        "assignment_source": str(repo["spec"]),
        "assignment_destination": str(repo["assignment"]),
    }
    mismatch = lifecycle.verify_seed(**args)
    assert mismatch["status"] == "blocked"
    assert not next(check for check in mismatch["checks"] if check["name"] == "assignment_bytes_match_control")["ok"]

    _git(path, "branch", "saved-seed", seed)
    _git(path, "checkout", "-B", TASK_BRANCH, base)
    (path / "alternative.txt").write_text("another child of base\n", encoding="utf-8")
    _commit(path, "alternative seed")
    diverged = lifecycle.verify_seed(**args, seed_sha=seed, allow_later_head=True)
    assert diverged["status"] == "blocked"
    assert not next(check for check in diverged["checks"] if check["name"] == "seed_ancestor")["ok"]


def test_batch_seed_verification_covers_all_material_and_later_head_ancestry(
    tmp_path: Path,
) -> None:
    repo = _integrated_batch_repo(tmp_path)
    path = Path(repo["repo"])
    seed = _integrated_seed(repo)
    args = {
        "repo_path": str(path),
        "control_sha": str(repo["control"]),
        "manifest_path": str(repo["manifest"]),
        "seed_sha": seed,
    }

    verified = lifecycle.verify_batch_seed(**args)
    assert verified["status"] == "verified"
    assert verified["task_order"] == [f"{number:04d}" for number in range(51, 61)]

    (path / "later.txt").write_text("later\n", encoding="utf-8")
    later = _commit(path, "later implementation")
    assert lifecycle.verify_batch_seed(**args)["status"] == "blocked"
    later_result = lifecycle.verify_batch_seed(**args, allow_later_head=True)
    assert later_result["status"] == "verified"
    assert later_result["head"] == later


def test_batch_seed_verification_rejects_missing_assignment(tmp_path: Path) -> None:
    repo = _integrated_batch_repo(tmp_path)
    seed = _integrated_seed(repo, omit_task="0058")

    result = lifecycle.verify_batch_seed(
        repo_path=str(repo["repo"]),
        control_sha=str(repo["control"]),
        manifest_path=str(repo["manifest"]),
        seed_sha=seed,
    )

    assert result["status"] == "blocked"
    material = next(
        check for check in result["checks"] if check["name"] == "complete_batch_material"
    )
    assert not material["ok"]
    assert next(item for item in material["actual"] if item["id"] == "0058")["ok"] is False


def test_batch_checkpoints_progress_in_order_and_bind_pr_ci_merge_heads(
    tmp_path: Path,
) -> None:
    repo = _integrated_batch_repo(tmp_path)
    path = Path(repo["repo"])
    state = tmp_path / "batch-state"
    lifecycle.write_batch_checkpoint(**_batch_checkpoint_args(repo, state, "preflight"))
    assert lifecycle.batch_checkpoint_status(
        repo_path=str(path),
        state_dir=str(state),
        control_sha=str(repo["control"]),
        manifest_path=str(repo["manifest"]),
    )["status"] == "current"
    seed = _integrated_seed(repo)
    lifecycle.write_batch_checkpoint(
        **_batch_checkpoint_args(repo, state, "seed", seed_sha=seed)
    )

    for task_id in (f"{number:04d}" for number in range(51, 61)):
        (path / "progress.txt").write_text(f"{task_id}\n", encoding="utf-8")
        _commit(path, f"checkpoint {task_id}")
        if task_id == "0051":
            assert lifecycle.batch_checkpoint_status(
                repo_path=str(path),
                state_dir=str(state),
                control_sha=str(repo["control"]),
                manifest_path=str(repo["manifest"]),
            )["status"] == "stale"
        lifecycle.write_batch_checkpoint(
            **_batch_checkpoint_args(repo, state, "task", task_id=task_id)
        )

    (path / "review.md").write_text("review\n", encoding="utf-8")
    _commit(path, "batch review")
    lifecycle.write_batch_checkpoint(**_batch_checkpoint_args(repo, state, "review"))
    lifecycle.write_batch_checkpoint(**_batch_checkpoint_args(repo, state, "final_local"))
    first_head = _git(path, "rev-parse", "HEAD")
    lifecycle.write_batch_checkpoint(
        **_batch_checkpoint_args(
            repo, state, "pr", pr_number=77, pr_head_sha=first_head
        )
    )

    (path / "progress.txt").write_text("0060 correction\n", encoding="utf-8")
    corrected_head = _commit(path, "correct 0060")
    lifecycle.write_batch_checkpoint(
        **_batch_checkpoint_args(
            repo, state, "task", task_id="0060", correction_count=1
        )
    )
    lifecycle.write_batch_checkpoint(**_batch_checkpoint_args(repo, state, "review"))
    lifecycle.write_batch_checkpoint(**_batch_checkpoint_args(repo, state, "final_local"))
    with pytest.raises(lifecycle.LifecycleError, match="exact current PR head"):
        lifecycle.write_batch_checkpoint(
            **_batch_checkpoint_args(repo, state, "ci", ci_head_sha=first_head)
        )
    lifecycle.write_batch_checkpoint(
        **_batch_checkpoint_args(
            repo, state, "pr", pr_number=77, pr_head_sha=corrected_head
        )
    )
    lifecycle.write_batch_checkpoint(
        **_batch_checkpoint_args(repo, state, "ci", ci_head_sha=corrected_head)
    )

    _git(path, "checkout", "main")
    _git(path, "merge", "--no-ff", "-m", "merge integrated batch", TASK_BRANCH)
    merge_sha = _git(path, "rev-parse", "HEAD")
    merged = lifecycle.write_batch_checkpoint(
        **_batch_checkpoint_args(repo, state, "merge", merge_sha=merge_sha)
    )["checkpoint"]

    assert merged["highest_event"] == "merge"
    assert merged["task_checkpoints"][-1]["correction_count"] == 1
    assert merged["pr_head_sha"] == corrected_head
    assert merged["ci_green_head"] == corrected_head
    assert merged["merge_sha"] == merge_sha
    assert lifecycle.batch_checkpoint_status(
        repo_path=str(path),
        state_dir=str(state),
        control_sha=str(repo["control"]),
        manifest_path=str(repo["manifest"]),
    )["status"] == "current"


def test_batch_checkpoint_rejects_skipped_duplicate_and_regressed_correction(
    tmp_path: Path,
) -> None:
    repo = _integrated_batch_repo(tmp_path)
    path = Path(repo["repo"])
    state = tmp_path / "batch-state"
    lifecycle.write_batch_checkpoint(**_batch_checkpoint_args(repo, state, "preflight"))
    seed = _integrated_seed(repo)
    lifecycle.write_batch_checkpoint(
        **_batch_checkpoint_args(repo, state, "seed", seed_sha=seed)
    )
    (path / "progress.txt").write_text("first\n", encoding="utf-8")
    _commit(path, "first checkpoint")

    with pytest.raises(lifecycle.LifecycleError, match="manifest order"):
        lifecycle.write_batch_checkpoint(
            **_batch_checkpoint_args(repo, state, "task", task_id="0052")
        )
    lifecycle.write_batch_checkpoint(
        **_batch_checkpoint_args(repo, state, "task", task_id="0051")
    )
    with pytest.raises(lifecycle.LifecycleError, match="advance count"):
        lifecycle.write_batch_checkpoint(
            **_batch_checkpoint_args(
                repo, state, "task", task_id="0051", correction_count=0
            )
        )


def test_batch_checkpoint_atomic_failure_and_malformed_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _integrated_batch_repo(tmp_path)
    path = Path(repo["repo"])
    state = tmp_path / "batch-state"
    first = lifecycle.write_batch_checkpoint(
        **_batch_checkpoint_args(repo, state, "preflight")
    )
    checkpoint_path = Path(first["checkpoint_path"])
    original = checkpoint_path.read_bytes()
    assert checkpoint_path.stat().st_mode & 0o777 == 0o600
    seed = _integrated_seed(repo)

    def fail_replace(_source, _destination):
        raise OSError("simulated batch rename failure")

    monkeypatch.setattr(lifecycle.os, "replace", fail_replace)
    with pytest.raises(OSError, match="simulated batch"):
        lifecycle.write_batch_checkpoint(
            **_batch_checkpoint_args(repo, state, "seed", seed_sha=seed)
        )
    assert checkpoint_path.read_bytes() == original
    assert not list(checkpoint_path.parent.glob("*.tmp"))

    monkeypatch.undo()
    payload = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    payload["highest_event"] = "merge"
    checkpoint_path.write_text(json.dumps(payload), encoding="utf-8")
    assert lifecycle.batch_checkpoint_status(
        repo_path=str(path),
        state_dir=str(state),
        control_sha=str(repo["control"]),
        manifest_path=str(repo["manifest"]),
    )["status"] == "invalid"


def test_checkpoint_phases_are_monotonic_and_corrections_keep_high_water_mark(tmp_path: Path) -> None:
    repo = _simple_repo(tmp_path)
    state = tmp_path / "state"
    common = {"repo_path": str(repo), "state_dir": str(state), "assignment": "0031"}

    for phase in ("preflight_ok", "seeded", "implementation_ready", "focused_green"):
        lifecycle.write_checkpoint(**common, phase=phase)
    with pytest.raises(lifecycle.LifecycleError, match="regression"):
        lifecycle.write_checkpoint(**common, phase="seeded")

    (repo / "implementation.py").write_text("# corrected\n", encoding="utf-8")
    _commit(repo, "implementation correction")
    corrected = lifecycle.write_checkpoint(
        **common,
        phase="implementation_ready",
        correction_iteration=1,
    )["checkpoint"]

    assert corrected["phase"] == "implementation_ready"
    assert corrected["highest_phase"] == "focused_green"
    assert corrected["correction_iteration"] == 1
    assert corrected["correction_history"][0]["iteration"] == 1
    assert [event["phase"] for event in corrected["phase_history"]][-2:] == [
        "focused_green",
        "implementation_ready",
    ]


def test_checkpoint_writes_atomic_private_file_and_preserves_old_state_on_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _simple_repo(tmp_path)
    state = tmp_path / "state"
    common = {"repo_path": str(repo), "state_dir": str(state), "assignment": "0031"}
    result = lifecycle.write_checkpoint(**common, phase="preflight_ok")
    path = Path(result["checkpoint_path"])
    original = path.read_bytes()
    assert path.stat().st_mode & 0o777 == 0o600

    def fail_replace(_source, _destination):
        raise OSError("simulated atomic rename failure")

    monkeypatch.setattr(lifecycle.os, "replace", fail_replace)
    with pytest.raises(OSError, match="simulated"):
        lifecycle.write_checkpoint(**common, phase="seeded")

    assert path.read_bytes() == original
    assert not list(path.parent.glob("*.tmp"))


def test_checkpoint_status_reports_stale_and_malformed_state(tmp_path: Path) -> None:
    repo = _simple_repo(tmp_path)
    state = tmp_path / "state"
    common = {"repo_path": str(repo), "state_dir": str(state), "assignment": "0031"}
    result = lifecycle.write_checkpoint(**common, phase="preflight_ok")
    path = Path(result["checkpoint_path"])

    (repo / "later.txt").write_text("later\n", encoding="utf-8")
    _commit(repo, "later commit")
    assert lifecycle.checkpoint_status(**common)["status"] == "stale"

    path.write_text("{not json", encoding="utf-8")
    assert lifecycle.checkpoint_status(**common)["status"] == "invalid"


def test_malformed_checkpoint_types_return_invalid_instead_of_crashing(tmp_path: Path) -> None:
    repo = _simple_repo(tmp_path)
    state = tmp_path / "state"
    common = {"repo_path": str(repo), "state_dir": str(state), "assignment": "0031"}
    result = lifecycle.write_checkpoint(**common, phase="preflight_ok")
    path = Path(result["checkpoint_path"])
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["phase"] = []
    path.write_text(json.dumps(payload), encoding="utf-8")

    assert lifecycle.checkpoint_status(**common)["status"] == "invalid"


def test_checkpoint_directory_inside_repository_is_rejected(tmp_path: Path) -> None:
    repo = _simple_repo(tmp_path)

    with pytest.raises(lifecycle.LifecycleError, match="outside"):
        lifecycle.write_checkpoint(
            repo_path=str(repo),
            state_dir=str(repo / ".state"),
            assignment="0031",
            phase="preflight_ok",
        )


def test_checkpoint_pr_metadata_and_merged_phase_are_consistent(tmp_path: Path) -> None:
    repo = _simple_repo(tmp_path)
    state = tmp_path / "state"
    common = {"repo_path": str(repo), "state_dir": str(state), "assignment": "0031"}
    head = _git(repo, "rev-parse", "HEAD")

    for phase in (
        "preflight_ok",
        "seeded",
        "implementation_ready",
        "focused_green",
        "canonical_green",
        "review_written",
    ):
        lifecycle.write_checkpoint(**common, phase=phase)
    lifecycle.write_checkpoint(
        **common,
        phase="pr_open",
        pr_number=91,
        pr_head_sha=head,
    )
    lifecycle.write_checkpoint(**common, phase="ci_green")
    merged = lifecycle.write_checkpoint(
        **common,
        phase="merged",
        merge_sha="b" * 40,
    )["checkpoint"]

    assert merged["pr_number"] == 91
    assert merged["pr_head_sha"] == head
    assert merged["merge_sha"] == "b" * 40
    assert lifecycle.checkpoint_status(**common)["status"] == "current"
    with pytest.raises(lifecycle.LifecycleError, match="terminal"):
        lifecycle.write_checkpoint(**common, phase="ci_green")


def test_checkpoint_loader_rejects_unrecorded_phase_regression(tmp_path: Path) -> None:
    repo = _simple_repo(tmp_path)
    state = tmp_path / "state"
    common = {"repo_path": str(repo), "state_dir": str(state), "assignment": "0031"}
    result = lifecycle.write_checkpoint(**common, phase="preflight_ok")
    path = Path(result["checkpoint_path"])
    payload = json.loads(path.read_text(encoding="utf-8"))
    head = payload["head"]
    timestamp = payload["updated_at"]
    payload["phase"] = "seeded"
    payload["highest_phase"] = "canonical_green"
    payload["phase_history"] = [
        {"phase": "preflight_ok", "correction_iteration": 0, "head": head, "timestamp": timestamp},
        {"phase": "canonical_green", "correction_iteration": 0, "head": head, "timestamp": timestamp},
        {"phase": "seeded", "correction_iteration": 0, "head": head, "timestamp": timestamp},
    ]
    path.write_text(json.dumps(payload), encoding="utf-8")

    assert lifecycle.checkpoint_status(**common)["status"] == "invalid"
