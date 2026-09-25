from __future__ import annotations

import json
from pathlib import Path

import pytest

from ah_there_it_is.promotion_report import (
    build_promotion_report,
    campaign_evidence_completeness,
    render_promotion_markdown,
    write_promotion_reports,
)


def _attempt(
    slot: str,
    *,
    pipeline: str = "live_eval",
    case_id: str = "quantity-removed-undo",
    passed: bool = True,
    check_kind: str = "item_quantity_truth",
    wall: float = 1.0,
    cost: float | None = None,
) -> dict:
    if pipeline == "model_probe":
        evidence = {"case_id": case_id, "passed": passed}
    else:
        metadata = {} if cost is None else {"cost_usd": cost}
        evidence = {
            "case_id": case_id,
            "status": "completed",
            "checks_passed": passed,
            "checks": [
                {
                    "kind": check_kind,
                    "ok": passed,
                    "detail": {"event_type": "item_undo_compensated"},
                }
            ],
            "wall_seconds": wall,
            "turns": [
                {
                    "rounds": 1,
                    "tool_trace": [
                        {"assistant": {"metadata": metadata, "tool_calls": []}}
                    ],
                }
            ],
        }
    return {
        "slot_id": slot,
        "pipeline": pipeline,
        "case_id": case_id,
        "repetition": int(slot.rsplit(":", 1)[1]),
        "completed": True,
        "evidence": evidence,
    }


def _campaign(
    *,
    model: str,
    live_passes: tuple[bool, bool] = (True, True),
    probe_passed: bool = True,
    check_kind: str = "item_quantity_truth",
    wall: float = 1.0,
    cost: float | None = None,
) -> dict:
    attempts = [
        _attempt(
            "live_eval:quantity-removed-undo:1",
            passed=live_passes[0],
            check_kind=check_kind,
            wall=wall,
            cost=cost,
        ),
        _attempt(
            "live_eval:quantity-removed-undo:2",
            passed=live_passes[1],
            check_kind=check_kind,
            wall=wall,
            cost=cost,
        ),
        _attempt(
            "model_probe:tool-contract:1",
            pipeline="model_probe",
            case_id="tool-contract",
            passed=probe_passed,
        ),
    ]
    return {
        "schema_version": "benchmark-result-v1",
        "campaign": {
            "schema_version": "benchmark-campaign-v1",
            "campaign_id": "promotion-fixture",
            "campaign_version": "1",
            "candidate": {"provider": "fake", "model": model, "config_label": "cfg"},
            "prompt": {"version": "p1", "file": "prompt.txt", "sha256": "a" * 64},
            "live_eval": {
                "file": "corpus.json",
                "version": "corpus-v1",
                "case_ids": ["quantity-removed-undo"],
            },
            "model_probe": {
                "file": "probe.json",
                "version": "probe-v1",
                "case_ids": ["tool-contract"],
            },
            "repetitions": 2,
            "delay_seconds": 0,
            "output": {"directory": "results", "file_prefix": model},
        },
        "execution_identity_hash": ("b" if model == "baseline" else "c") * 64,
        "provider": {
            "provider": "fake",
            "model": model,
            "config_label": "cfg",
            "config_hash": "d" * 64,
            "config": {"temperature": 0},
        },
        "prompt_version": "p1",
        "prompt_hash": "a" * 64,
        "corpus_version": "corpus-v1",
        "corpus_hash": "e" * 64,
        "probe_suite_version": "probe-v1",
        "probe_suite_hash": "f" * 64,
        "completed": True,
        "attempts": attempts,
    }


def test_promotion_report_passes_only_complete_correctness_evidence() -> None:
    baseline = _campaign(model="baseline")
    candidate = _campaign(model="candidate")
    report = build_promotion_report(
        baseline,
        candidate,
        baseline_evidence_file="baseline.json",
        candidate_evidence_file="candidate.json",
        generated_at="2026-01-01T00:00:00Z",
    )

    assert report["schema_version"] == "promotion-report-v1"
    assert report["promotion_mode"] == "manual"
    assert report["hard_gate_passed"] is True
    assert report["hard_gate_reasons"] == []
    assert report["evidence_completeness"]["baseline"]["complete"] is True
    assert report["evidence_completeness"]["candidate"]["complete"] is True
    assert report["baseline"]["config"] == {"temperature": 0}
    assert report["candidate"]["prompt_hash"] == "a" * 64
    assert report["evidence_files"]["candidate_campaign"] == "candidate.json"


@pytest.mark.parametrize(
    ("mutator", "expected_gate"),
    [
        (lambda campaign: campaign["attempts"].__setitem__(2, _attempt("model_probe:tool-contract:1", pipeline="model_probe", case_id="tool-contract", passed=False)), "provider_tool_contract"),
        (lambda campaign: campaign["attempts"].__setitem__(0, _attempt("live_eval:quantity-removed-undo:1", passed=False, check_kind="no_mutation")), "write_target_safety"),
        (lambda campaign: campaign["attempts"].__setitem__(0, _attempt("live_eval:quantity-removed-undo:1", passed=False, check_kind="item_event")), "mutation_correctness"),
        (lambda campaign: campaign["attempts"].__setitem__(0, _attempt("live_eval:quantity-removed-undo:1", passed=False, check_kind="item_quantity_truth")), "quantity_lifecycle_undo"),
    ],
)
def test_promotion_hard_gate_fails_for_required_correctness_categories(mutator, expected_gate: str) -> None:
    baseline = _campaign(model="baseline")
    candidate = _campaign(model="candidate")
    mutator(candidate)

    report = build_promotion_report(baseline, candidate, generated_at="2026-01-01T00:00:00Z")

    assert report["hard_gate_passed"] is False
    gates = {reason["gate"] for reason in report["hard_gate_reasons"]}
    assert expected_gate in gates
    assert "application_checks" in gates or expected_gate == "provider_tool_contract"


def test_promotion_hard_gate_fails_closed_when_declared_evidence_is_incomplete() -> None:
    baseline = _campaign(model="baseline")
    candidate = _campaign(model="candidate")
    candidate["attempts"].pop(1)
    candidate["completed"] = False

    completeness = campaign_evidence_completeness(candidate)
    report = build_promotion_report(baseline, candidate, generated_at="2026-01-01T00:00:00Z")

    assert completeness["complete"] is False
    assert completeness["missing_attempt_refs"] == ["live_eval:quantity-removed-undo:2"]
    assert report["hard_gate_passed"] is False
    assert any(reason["gate"] == "evidence_completeness" for reason in report["hard_gate_reasons"])


def test_promotion_cost_and_latency_are_reported_but_are_not_hard_gates() -> None:
    baseline = _campaign(model="baseline", wall=1.0, cost=0.01)
    candidate = _campaign(model="candidate", wall=5.0, cost=0.05)

    report = build_promotion_report(baseline, candidate, generated_at="2026-01-01T00:00:00Z")

    assert report["hard_gate_passed"] is True
    assert report["operational_comparison"]["wall_seconds_total"] == 8.0
    assert report["operational_comparison"]["cost_usd"] == 0.08
    metrics = {(item["area"], item["metric"]) for item in report["known_regressions"]}
    assert ("operations", "wall_seconds_total") in metrics
    assert ("operations", "cost_usd") in metrics


def test_promotion_report_records_intermittent_failure_and_regression_evidence() -> None:
    baseline = _campaign(model="baseline")
    candidate = _campaign(model="candidate", live_passes=(True, False))

    report = build_promotion_report(baseline, candidate, generated_at="2026-01-01T00:00:00Z")

    assert report["hard_gate_passed"] is False
    assert report["intermittent_failures"]["candidate"] == [
        "live_eval:quantity-removed-undo:1",
        "live_eval:quantity-removed-undo:2",
    ]
    hard_regressions = [item for item in report["known_regressions"] if item["area"] == "hard_correctness"]
    assert hard_regressions
    assert hard_regressions[0]["candidate_attempt_refs"]


def test_promotion_report_json_markdown_are_deterministic_and_report_only(tmp_path: Path) -> None:
    report = build_promotion_report(
        _campaign(model="baseline"),
        _campaign(model="candidate"),
        generated_at="2026-01-01T00:00:00Z",
    )
    json_path, md_path = write_promotion_reports(
        report, output_dir=tmp_path / "promotion-v1", file_prefix="candidate"
    )
    markdown = md_path.read_text(encoding="utf-8")
    loaded = json.loads(json_path.read_text(encoding="utf-8"))

    assert loaded == report
    assert markdown == render_promotion_markdown(report)
    assert "Promotion mode: `manual`" in markdown
    assert "does not edit provider/model configuration" in markdown
    assert not (tmp_path / ".env").exists()
