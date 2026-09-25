from __future__ import annotations

import json
from pathlib import Path

import pytest

from ah_there_it_is.benchmark_compare import (
    aggregate_campaign,
    compare_campaigns,
    render_comparison_markdown,
    write_comparison_reports,
)


def _attempt(
    slot: str,
    *,
    pipeline: str = "live_eval",
    case_id: str = "quantity-ru-immediate-undo",
    passed: bool = True,
    wall: float = 1.0,
    check_kind: str = "item_event",
    token_count: int | None = None,
    cost: float | None = None,
    rate_limited: bool = False,
) -> dict:
    if pipeline == "model_probe":
        evidence = {"case_id": case_id, "passed": passed}
    else:
        metadata: dict = {}
        if token_count is not None:
            metadata["usage"] = {"total_tokens": token_count}
        if cost is not None:
            metadata["cost_usd"] = cost
        if rate_limited:
            metadata["transport"] = {"retry_events": [{"status": 429}]}
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
                    "rounds": 2,
                    "tool_trace": [
                        {
                            "assistant": {
                                "metadata": metadata,
                                "tool_calls": [{"name": "x"}],
                            }
                        }
                    ],
                }
            ],
        }
    return {
        "slot_id": slot,
        "pipeline": pipeline,
        "case_id": case_id,
        "repetition": 1,
        "completed": True,
        "evidence": evidence,
    }


def _campaign(*attempts: dict, provider: str = "fake", model: str = "m1") -> dict:
    return {
        "schema_version": "benchmark-result-v1",
        "campaign": {
            "campaign_id": "bench",
            "campaign_version": "1",
            "live_eval": {"case_ids": ["quantity-ru-immediate-undo"]},
            "model_probe": {"case_ids": ["tool-basic"]},
            "repetitions": 1,
        },
        "execution_identity_hash": "x" * 64,
        "provider": {
            "provider": provider,
            "model": model,
            "config_label": "cfg",
            "config_hash": "c" * 64,
            "config": {"temperature": 0},
        },
        "prompt_version": "p1",
        "prompt_hash": "a" * 64,
        "corpus_version": "c1",
        "corpus_hash": "b" * 64,
        "probe_suite_version": "s1",
        "probe_suite_hash": "d" * 64,
        "completed": True,
        "attempts": list(attempts),
    }


def test_aggregate_keeps_hard_behavior_operations_and_refs_separate() -> None:
    campaign = _campaign(
        _attempt("live:1", passed=False, token_count=90, cost=0.02, rate_limited=True),
        _attempt("live:2", passed=True, token_count=70, cost=0.01),
        _attempt("probe:1", pipeline="model_probe", case_id="tool-basic", passed=False),
    )
    result = aggregate_campaign(campaign)

    hard = result["hard_correctness"]
    assert hard["passed"] is False
    assert hard["categories"]["provider_tool_contract"]["attempt_refs"] == ["probe:1"]
    assert hard["categories"]["mutation_correctness"]["attempt_refs"] == ["live:1"]
    assert hard["categories"]["quantity_lifecycle_undo"]["attempt_refs"] == ["live:1"]
    assert result["behavior"]["passed_attempts"] == 1
    assert result["behavior"]["rounds"] == 4
    assert result["behavior"]["tool_calls"] == 2
    assert result["operations"]["total_tokens"] == 160
    assert result["operations"]["cost_usd"] == 0.03
    assert result["operations"]["rate_limit_events"] == 1
    assert result["operations"]["attempt_refs"]["tokens"] == ["live:1", "live:2"]
    assert result["operations"]["attempt_refs"]["cost"] == ["live:1", "live:2"]
    assert result["behavior"]["attempt_refs"]["rounds"] == ["live:1", "live:2"]
    assert set(result["all_attempt_refs"]) == {"live:1", "live:2", "probe:1"}


def test_repeatability_reports_disagreement_and_intermittent_failure() -> None:
    campaign = _campaign(
        _attempt("live:1", passed=True),
        _attempt("live:2", passed=False),
    )
    aggregate = aggregate_campaign(campaign)
    repeat = aggregate["repeatability"]

    assert repeat["repeated_case_count"] == 1
    assert repeat["disagreement_rate"] == 1.0
    assert repeat["intermittent_failure_rate"] == 1.0
    assert repeat["cases"][0]["attempt_refs"] == ["live:1", "live:2"]


def test_compare_hard_regression_fails_gate_even_when_latency_and_cost_improve() -> None:
    baseline = _campaign(_attempt("base:1", passed=True, wall=2.0, cost=0.05))
    candidate = _campaign(_attempt("cand:1", passed=False, wall=0.5, cost=0.01), model="m2")

    comparison = compare_campaigns(baseline, candidate, generated_at="2026-01-01T00:00:00Z")

    assert comparison["hard_gate"]["passed"] is False
    assert comparison["hard_gate"]["hard_regressions"]
    assert comparison["deltas"]["operations_candidate_minus_baseline"]["wall_seconds_total"] == -1.5
    assert comparison["deltas"]["operations_candidate_minus_baseline"]["cost_usd"] == -0.04
    assert "score" not in comparison
    assert "winner" not in json.dumps(comparison).casefold()



def test_unsupported_fact_evidence_is_a_hard_failure() -> None:
    attempt = _attempt("live:unsupported", passed=True)
    attempt["evidence"]["unsupported_fact_failures"] = 1
    aggregate = aggregate_campaign(_campaign(attempt))

    assert aggregate["hard_correctness"]["passed"] is False
    assert aggregate["hard_correctness"]["categories"]["unsupported_facts"]["attempt_refs"] == [
        "live:unsupported"
    ]


def test_comparison_rejects_different_workload_selection_or_repetitions() -> None:
    baseline = _campaign(_attempt("base:1"))
    candidate = _campaign(_attempt("cand:1"), model="m2")
    candidate["campaign"]["live_eval"]["case_ids"] = ["different-case"]
    with pytest.raises(ValueError, match="live_case_ids"):
        compare_campaigns(baseline, candidate)

    candidate = _campaign(_attempt("cand:1"), model="m2")
    candidate["campaign"]["repetitions"] = 2
    with pytest.raises(ValueError, match="repetitions"):
        compare_campaigns(baseline, candidate)


def test_trace_metrics_sum_mixed_explicit_and_derived_total_tokens() -> None:
    first = _attempt("live:1", passed=True)
    first["evidence"]["turns"] = [
        {
            "rounds": 1,
            "tool_trace": [
                {"assistant": {"metadata": {"usage": {"total_tokens": 100}}, "tool_calls": []}},
                {
                    "assistant": {
                        "metadata": {"usage": {"prompt_tokens": 40, "completion_tokens": 20}},
                        "tool_calls": [],
                    }
                },
            ],
        }
    ]
    aggregate = aggregate_campaign(_campaign(first))
    assert aggregate["operations"]["total_tokens"] == 160
    assert aggregate["operations"]["prompt_tokens"] == 40
    assert aggregate["operations"]["completion_tokens"] == 20

def test_unavailable_cost_and_tokens_are_null_not_zero() -> None:
    aggregate = aggregate_campaign(_campaign(_attempt("live:1", passed=True)))

    assert aggregate["operations"]["total_tokens"] is None
    assert aggregate["operations"]["cost_usd"] is None
    assert aggregate["operations"]["token_data_available"] is False
    assert aggregate["operations"]["cost_data_available"] is False


def test_comparison_json_and_markdown_keep_evidence_references(tmp_path: Path) -> None:
    comparison = compare_campaigns(
        _campaign(_attempt("base:1", passed=True)),
        _campaign(_attempt("cand:1", passed=False), model="m2"),
        generated_at="2026-01-01T00:00:00Z",
    )
    json_path = tmp_path / "comparison.json"
    md_path = tmp_path / "comparison.md"
    write_comparison_reports(comparison, json_path=json_path, markdown_path=md_path)

    loaded = json.loads(json_path.read_text(encoding="utf-8"))
    markdown = md_path.read_text(encoding="utf-8")
    assert loaded["schema_version"] == "benchmark-comparison-v1"
    assert "cand:1" in json.dumps(loaded)
    assert "cand:1" in markdown
    assert "Hard gate passed: `false`" in markdown
    assert "no overall score" in markdown
    assert render_comparison_markdown(comparison) == markdown


def test_comparison_requires_identical_evaluation_evidence_identity() -> None:
    baseline = _campaign(_attempt("base:1"))
    candidate = _campaign(_attempt("cand:1"), model="m2")
    candidate["corpus_hash"] = "e" * 64

    with pytest.raises(ValueError, match="corpus_hash"):
        compare_campaigns(baseline, candidate)
