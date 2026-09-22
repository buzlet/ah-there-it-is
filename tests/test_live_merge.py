from __future__ import annotations

from copy import deepcopy

import pytest

from ah_there_it_is.live_merge import merge_reports


def _report(case_id: str, trial: int, *, prompt_hash: str = "a" * 64) -> dict:
    return {
        "corpus_version": "inventory-corpus-v1",
        "fixture_version": "inventory-fixture-v1",
        "prompt_version": "inventory-v1",
        "prompt_hash": prompt_hash,
        "provider": {
            "provider": "groq",
            "model": "qwen",
            "config": {"temperature": 0.6},
        },
        "repetitions": 1,
        "trial_start": trial,
        "cases": [
            {
                "case_id": case_id,
                "trial": trial,
                "execution_id": f"{case_id}#r{trial}",
                "status": "completed",
                "error": None,
                "turns": [],
                "checks": [{"kind": "no_mutation", "ok": True}],
                "checks_passed": True,
                "wall_seconds": 1.0,
            }
        ],
        "summary": {},
    }


def test_merge_reports_combines_resumed_trials_and_recomputes_summary() -> None:
    first = _report("find-01", 1)
    second = _report("find-01", 2)
    third = _report("ambiguity-01", 2)

    merged = merge_reports([first, second, third])

    assert merged["merged_from_reports"] == 3
    assert merged["trial_start"] == 1
    assert merged["repetitions"] == 2
    assert [case["execution_id"] for case in merged["cases"]] == [
        "find-01#r1",
        "ambiguity-01#r2",
        "find-01#r2",
    ]
    assert merged["summary"] == {
        "count": 3,
        "completed": 3,
        "failed": 0,
        "automatically_checked": 3,
        "automatic_checks_passed": 3,
        "manual_review_required": 0,
    }


def test_merge_reports_deduplicates_identical_execution() -> None:
    report = _report("find-01", 1)

    merged = merge_reports([report, deepcopy(report)])

    assert len(merged["cases"]) == 1


def test_merge_reports_rejects_conflicting_duplicate_execution() -> None:
    first = _report("find-01", 1)
    second = deepcopy(first)
    second["cases"][0]["wall_seconds"] = 2.0

    with pytest.raises(ValueError, match="conflicting execution"):
        merge_reports([first, second])


def test_merge_reports_rejects_different_identity() -> None:
    first = _report("find-01", 1)
    second = _report("find-01", 2, prompt_hash="b" * 64)

    with pytest.raises(ValueError, match="different corpus"):
        merge_reports([first, second])
