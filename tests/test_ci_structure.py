from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_ordinary_ci_uses_fast_plan_and_does_not_run_extended_suite() -> None:
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "test-fast-coverage" in workflow
    assert "test-extended-coverage" not in workflow
    assert "make PYTHON=python scenario-eval" not in workflow
    assert "workflow_dispatch" not in workflow


def test_extended_ci_is_explicit_and_runs_complete_plan() -> None:
    workflow = (ROOT / ".github/workflows/extended-ci.yml").read_text(encoding="utf-8")
    assert "workflow_dispatch:" in workflow
    assert "pull_request:" not in workflow
    assert "push:" not in workflow
    assert "test-extended-coverage" in workflow
    assert "make PYTHON=python scenario-eval" in workflow
    assert 'test "$(git rev-parse HEAD)" = "$GITHUB_SHA"' in workflow


def test_sandbox_bundle_includes_v9_executor_profiles() -> None:
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "common designs planning batches assignments reviews executors" in workflow
    assert "sandbox-bundle/agent-tasks/executors/chatgpt-sandbox.md" in workflow


def test_makefile_exposes_fast_profile_and_complete_extended_entrypoints() -> None:
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    for target in (
        "test-fast:",
        "test-profile:",
        "test-extended:",
        "test-fast-coverage:",
        "test-extended-coverage:",
    ):
        assert target in makefile
    assert '-m "not extended"' in makefile
    assert "--fail-under=83.00" in makefile
