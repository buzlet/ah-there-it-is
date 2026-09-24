from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from tools.agent import ci_waiter, codex_session, execution_recovery, lifecycle_checkpoints


TASK_BRANCH = "feat/agent-test-recovery"
CONTROL_BRANCH = "queue/test-recovery-control"
TASK_ORDER = ["0030", "0031", "0032", "0033", "0034"]
MANIFEST_PATH = "agent-tasks/batches/test-recovery/manifest.md"


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


def _test_repo(tmp_path: Path) -> dict[str, str | Path]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "--initial-branch=main")
    _git(repo, "config", "user.name", "Recovery Test")
    _git(repo, "config", "user.email", "recovery@example.invalid")
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    base = _commit(repo, "base")
    _git(repo, "remote", "add", "origin", "https://example.invalid/repo.git")
    _git(repo, "update-ref", "refs/remotes/origin/main", base)

    _git(repo, "checkout", "-b", CONTROL_BRANCH)
    (repo / "agent-tasks/batches/test-recovery").mkdir(parents=True)
    manifest_lines = [
        "# Recovery test batch",
        "",
        "Batch ID: `test-recovery`",
        "",
    ]
    for task_id in TASK_ORDER:
        branch = TASK_BRANCH if task_id == "0034" else f"feat/test-{task_id}"
        source = f"agent-tasks/batches/test-recovery/{task_id}-task.md"
        destination = f"agent-tasks/assignments/{task_id}-task.md"
        manifest_lines.extend(
            [
                f"### {task_id} — recovery test task",
                "",
                f"Branch: `{branch}`",
                f"Spec source: `{source}`",
                f"Assignment destination: `{destination}`",
                "",
            ]
        )
        spec = f"# Exact assignment {task_id}\n\nKeep these bytes intact: `$(touch /tmp/not-created)`\n"
        spec_path = repo / source
        spec_path.parent.mkdir(parents=True, exist_ok=True)
        spec_path.write_bytes(spec.encode())
    manifest = repo / MANIFEST_PATH
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text("\n".join(manifest_lines), encoding="utf-8")
    control = _commit(repo, "control manifest and exact tasks")
    _git(repo, "update-ref", f"refs/remotes/origin/{CONTROL_BRANCH}", control)

    _git(repo, "checkout", "main")
    _git(repo, "checkout", "-b", TASK_BRANCH, base)
    (repo / "seed.txt").write_text("immutable seed\n", encoding="utf-8")
    seed = _commit(repo, "immutable task seed")
    return {
        "repo": repo,
        "base": base,
        "control": control,
        "seed": seed,
        "state": tmp_path / "external-state",
    }


def _materialize(
    values: dict[str, str | Path],
    output: Path,
    *,
    continuation_from: str | None = None,
    continuation_state_file: Path | None = None,
) -> dict:
    return execution_recovery.materialize_prompt(
        repo_path=str(values["repo"]),
        control_sha=str(values["control"]),
        manifest_path=MANIFEST_PATH,
        task_id="0034",
        task_order=TASK_ORDER,
        start_main_sha=str(values["base"]),
        output_path=str(output),
        continuation_from=continuation_from,
        continuation_state_file=(
            str(continuation_state_file) if continuation_state_file is not None else None
        ),
    )


def _fake_codex(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path, Path]:
    codex = tmp_path / "fake-codex"
    starts = tmp_path / "codex-starts.log"
    mode = tmp_path / "codex-mode"
    mode.write_text("block", encoding="utf-8")
    codex.write_text(
        "#!" + sys.executable + "\n"
        "import hashlib, json, os, pathlib, sys, time\n"
        "if '--version' in sys.argv:\n"
        "    print('fake-codex 1')\n"
        "    raise SystemExit(0)\n"
        "prompt = sys.stdin.buffer.read()\n"
        "with open(os.environ['FAKE_CODEX_STARTS'], 'ab') as stream:\n"
        "    stream.write(hashlib.sha256(prompt).hexdigest().encode() + b'\\n')\n"
        "mode = pathlib.Path(os.environ['FAKE_CODEX_MODE']).read_text().strip()\n"
        "if mode == 'block':\n"
        "    while True:\n"
        "        time.sleep(0.05)\n"
        "elif mode == 'complete':\n"
        "    raise SystemExit(0)\n"
        "raise SystemExit(0)\n",
        encoding="utf-8",
    )
    codex.chmod(0o700)
    monkeypatch.setenv("FAKE_CODEX_STARTS", str(starts))
    monkeypatch.setenv("FAKE_CODEX_MODE", str(mode))
    monkeypatch.setenv("TEST_SECRET_SENTINEL", "sentinel-must-not-be-copied")
    return codex, starts, mode


def _wait_until(predicate, *, timeout: float = 8.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.02)
    raise AssertionError("condition did not become true before the bounded test timeout")


def _start_from_short_lived_controller(**kwargs) -> dict:
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])
    script = (
        "import json, sys\n"
        "from tools.agent import execution_recovery\n"
        "print(json.dumps(execution_recovery.start_run(**json.loads(sys.argv[1]))))\n"
    )
    completed = subprocess.run(
        [sys.executable, "-c", script, json.dumps(kwargs)],
        cwd=kwargs["repo_path"],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=15,
        env=environment,
    )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


def test_recovery_prevents_duplicates_and_continues_only_after_termination(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    values = _test_repo(tmp_path)
    repo = Path(values["repo"])
    state = Path(values["state"])
    prompt = tmp_path / "prompts/0034-initial.md"
    _materialize(values, prompt)
    codex, starts, mode = _fake_codex(tmp_path, monkeypatch)

    first = _start_from_short_lived_controller(
        repo_path=str(repo),
        branch=TASK_BRANCH,
        run_id="controller-run-1",
        prompt_file=str(prompt),
        state_dir=str(state),
        control_sha=str(values["control"]),
        task_id="0034",
        codex_bin=str(codex),
    )
    assert first["status"] == "running"
    _wait_until(lambda: starts.exists() and len(starts.read_text().splitlines()) == 1)

    # A fresh controller observes the detached run after the initiating call exits.
    restarted_controller_status = execution_recovery.status_run(
        repo_path=str(repo), branch=TASK_BRANCH, state_dir=str(state)
    )
    assert restarted_controller_status["status"] == "running"
    assert restarted_controller_status["recommendation"] == "keep_observing_existing_lifecycle"

    duplicate = execution_recovery.start_run(
        repo_path=str(repo),
        branch=TASK_BRANCH,
        run_id="controller-run-duplicate",
        prompt_file=str(prompt),
        state_dir=str(state),
        control_sha=str(values["control"]),
        task_id="0034",
        codex_bin=str(codex),
    )
    assert duplicate["status"] == "already_running"
    assert len(starts.read_text().splitlines()) == 1

    checkpoint = lifecycle_checkpoints.write_checkpoint(
        repo_path=str(repo),
        state_dir=str(state / "checkpoints"),
        assignment="0034",
        phase="canonical_green",
        expected_branch=TASK_BRANCH,
    )
    checkpoint_path = Path(checkpoint["checkpoint_path"])
    assert json.loads(checkpoint_path.read_text())["highest_phase"] == "canonical_green"

    continuation_state = {
        "branch": TASK_BRANCH,
        "branch_head": str(values["seed"]),
        "main_head": str(values["base"]),
        "pr_number": None,
        "pr_head_sha": None,
        "pr_state": "not_created",
        "ci_state": "not_started",
        "lifecycle_phase": "canonical_green",
    }
    continuation_state_file = state / "recovery-state.json"
    continuation_state_file.parent.mkdir(parents=True, exist_ok=True)
    continuation_state_file.write_text(json.dumps(continuation_state), encoding="utf-8")
    continuation_prompt = tmp_path / "prompts/0034-continuation.md"
    _materialize(
        values,
        continuation_prompt,
        continuation_from="controller-run-1",
        continuation_state_file=continuation_state_file,
    )
    early_continuation = execution_recovery.start_run(
        repo_path=str(repo),
        branch=TASK_BRANCH,
        run_id="controller-run-2",
        prompt_file=str(continuation_prompt),
        state_dir=str(state),
        control_sha=str(values["control"]),
        task_id="0034",
        continuation_from="controller-run-1",
        codex_bin=str(codex),
    )
    assert early_continuation["status"] == "already_running"
    assert len(starts.read_text().splitlines()) == 1

    terminated = codex_session.terminate_run(
        run_id="controller-run-1",
        state_dir=str(state / "codex-runs"),
        grace_seconds=1.0,
    )
    assert terminated["status"] == "terminated"
    _wait_until(
        lambda: not execution_recovery.status_run(
            repo_path=str(repo), branch=TASK_BRANCH, state_dir=str(state)
        )["lock_held"]
    )

    mode.write_text("complete", encoding="utf-8")
    continuation = execution_recovery.start_run(
        repo_path=str(repo),
        branch=TASK_BRANCH,
        run_id="controller-run-2",
        prompt_file=str(continuation_prompt),
        state_dir=str(state),
        control_sha=str(values["control"]),
        task_id="0034",
        continuation_from="controller-run-1",
        codex_bin=str(codex),
    )
    assert continuation["status"] == "running"
    _wait_until(
        lambda: codex_session.status_run(
            run_id="controller-run-2", state_dir=str(state / "codex-runs")
        )["status"]
        == "completed"
    )
    assert len(starts.read_text().splitlines()) == 2
    assert (state / "codex-runs/controller-run-2/stdout.jsonl").read_bytes() == b""

    # The recovery observer only reads checkpoints; it cannot write a lower phase.
    (repo / "implementation.txt").write_text("implementation commit\n", encoding="utf-8")
    _commit(repo, "implementation commit")
    execution_recovery.status_run(
        repo_path=str(repo), branch=TASK_BRANCH, state_dir=str(state)
    )
    assert json.loads(checkpoint_path.read_text())["highest_phase"] == "canonical_green"

    _git(repo, "checkout", "main")
    _git(repo, "merge", "--no-ff", TASK_BRANCH, "-m", "merge task branch")
    _git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
    merged = execution_recovery.status_run(
        repo_path=str(repo), branch=TASK_BRANCH, state_dir=str(state)
    )
    assert merged["status"] == "merged"
    assert merged["git"]["status"] == "merged"

    all_state = b"".join(path.read_bytes() for path in state.rglob("*") if path.is_file())
    assert b"sentinel-must-not-be-copied" not in all_state
    assert state.is_relative_to(tmp_path)
    assert not state.is_relative_to(repo)
    assert prompt.is_relative_to(tmp_path)
    assert not prompt.is_relative_to(repo)


def test_prompt_uses_exact_control_bytes_and_is_immutable_outside_worktree(tmp_path: Path) -> None:
    values = _test_repo(tmp_path)
    repo = Path(values["repo"])
    output = tmp_path / "state/prompts/issued.md"

    result = _materialize(values, output)

    source = subprocess.run(
        ["git", "-C", str(repo), "show", f"{values['control']}:agent-tasks/batches/test-recovery/0034-task.md"],
        check=True,
        stdout=subprocess.PIPE,
    ).stdout
    prompt_bytes = output.read_bytes()
    assert b"----- BEGIN EXACT ASSIGNMENT BYTES -----\n" + source in prompt_bytes
    assert result["spec_sha256"] == hashlib.sha256(source).hexdigest()
    assert output.stat().st_mode & 0o777 == 0o600
    with pytest.raises(execution_recovery.RecoveryError, match="already exists"):
        _materialize(values, output)


def test_git_reconcile_reports_unexpected_main_advance(tmp_path: Path) -> None:
    values = _test_repo(tmp_path)
    repo = Path(values["repo"])
    _git(repo, "checkout", "main")
    (repo / "external.txt").write_text("unrelated main advance\n", encoding="utf-8")
    new_main = _commit(repo, "unexpected main advance")
    _git(repo, "update-ref", "refs/remotes/origin/main", new_main)

    result = execution_recovery.reconcile_git(
        repo_path=str(repo),
        branch=TASK_BRANCH,
        base_sha=str(values["base"]),
    )

    assert result["status"] == "external_main_advance"
    assert result["branch_head"] == values["seed"]
    assert result["main_head"] == new_main


def test_unseeded_task_branch_is_not_mistaken_for_a_merge(tmp_path: Path) -> None:
    values = _test_repo(tmp_path)
    repo = Path(values["repo"])
    _git(repo, "branch", "feat/test-without-seed", str(values["base"]))

    result = execution_recovery.reconcile_git(
        repo_path=str(repo),
        branch="feat/test-without-seed",
        base_sha=str(values["base"]),
    )

    assert result["status"] == "seed_missing"


def test_seed_only_merge_is_not_reported_as_completed_assignment(tmp_path: Path) -> None:
    values = _test_repo(tmp_path)
    repo = Path(values["repo"])
    _git(repo, "checkout", "main")
    _git(repo, "checkout", "-b", "feat/seed-only", str(values["base"]))
    (repo / "seed-only.txt").write_text("seed only\n", encoding="utf-8")
    _commit(repo, "immutable seed only")
    _git(repo, "checkout", "main")
    _git(repo, "merge", "--no-ff", "feat/seed-only", "-m", "merge seed only")
    _git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")

    result = execution_recovery.reconcile_git(
        repo_path=str(repo),
        branch="feat/seed-only",
        base_sha=str(values["base"]),
    )

    assert result["status"] == "seed_only_merged"


def test_bounded_waiter_observes_queued_checks_with_fake_gh(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    head = "a" * 40
    calls = tmp_path / "fake-gh-calls.jsonl"
    gh = tmp_path / "fake-gh"
    gh.write_text(
        "#!" + sys.executable + "\n"
        "import json, os, sys\n"
        "args = sys.argv[1:]\n"
        "with open(os.environ['FAKE_GH_CALLS'], 'a') as stream:\n"
        "    stream.write(json.dumps(args) + '\\n')\n"
        "route = args[-1]\n"
        "if '/pulls/' in route:\n"
        "    value = {'head': {'sha': os.environ['FAKE_GH_HEAD']}}\n"
        "elif '/check-runs?' in route:\n"
        "    value = [{'total_count': 1, 'check_runs': [{'name': 'CI', 'status': 'queued', 'conclusion': None}]}]\n"
        "elif '/status?' in route:\n"
        "    value = [{'state': 'pending', 'statuses': [{'context': 'CI', 'state': 'pending'}]}]\n"
        "else:\n"
        "    raise SystemExit(3)\n"
        "print(json.dumps(value))\n",
        encoding="utf-8",
    )
    gh.chmod(0o700)
    monkeypatch.setenv("FAKE_GH_CALLS", str(calls))
    monkeypatch.setenv("FAKE_GH_HEAD", head)

    class Clock:
        now = 0.0

        def __call__(self) -> float:
            return self.now

        def sleep(self, seconds: float) -> None:
            self.now += seconds

    clock = Clock()
    state_dir = tmp_path / "external-ci-state"
    result = ci_waiter.wait_for_checks(
        repository="test/repo",
        pr_number=17,
        expected_head_sha=head,
        timeout_seconds=2.0,
        poll_interval_seconds=1.0,
        registration_grace_seconds=0.0,
        state_dir=str(state_dir),
        gh_bin=str(gh),
        clock=clock,
        sleeper=clock.sleep,
    )

    assert result["status"] == "timed_out"
    assert any(check["status"] == "queued" for check in result["observed_checks"])
    recorded_calls = [json.loads(line) for line in calls.read_text().splitlines()]
    assert recorded_calls
    assert all(call[0] == "api" for call in recorded_calls)
    assert state_dir.is_dir()
