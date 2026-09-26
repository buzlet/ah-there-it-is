from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_ordinary_ci_uses_parallel_fast_plan_without_coverage_or_extended_suite() -> None:
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "test-fast-parallel" in workflow
    assert "TEST_WORKERS=4" in workflow
    assert "test-fast-coverage" not in workflow
    assert "test-extended-coverage" not in workflow
    assert "coverage>=" not in workflow
    assert "make PYTHON=python scenario-eval" not in workflow
    assert "workflow_dispatch" not in workflow


def test_extended_ci_is_manual_or_daily_and_runs_complete_coverage_plan() -> None:
    workflow = (ROOT / ".github/workflows/extended-ci.yml").read_text(encoding="utf-8")
    assert "workflow_dispatch:" in workflow
    assert "schedule:" in workflow
    assert "pull_request:" not in workflow
    assert "push:" not in workflow
    assert "target_sha:" in workflow
    assert "required: true" in workflow
    assert "application-extended-ci" in workflow
    assert "should_run" in workflow
    assert 'ref: ${{ env.TARGET_SHA }}' in workflow
    assert 'test "$(git rev-parse HEAD)" = "$TARGET_SHA"' in workflow
    assert "test-extended-coverage" in workflow
    assert "make PYTHON=python scenario-eval" in workflow
    assert "statuses: write" in workflow
    assert "Mark exact SHA as deep-verified" in workflow


def test_sandbox_bundle_includes_v9_executor_profiles() -> None:
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "common designs planning batches assignments reviews executors" in workflow
    assert "sandbox-bundle/agent-tasks/executors/chatgpt-sandbox.md" in workflow


def test_makefile_exposes_parallel_fast_and_complete_extended_entrypoints() -> None:
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    for target in (
        "test-fast:",
        "test-fast-parallel:",
        "test-profile:",
        "test-extended:",
        "test-fast-coverage:",
        "test-extended-coverage:",
    ):
        assert target in makefile
    assert '-m "not extended"' in makefile
    assert '--dist=worksteal' in makefile
    assert "--fail-under=83.00" in makefile
