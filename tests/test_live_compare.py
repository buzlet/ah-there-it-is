from __future__ import annotations

from ah_there_it_is.live_compare import compare_reports


def _report(
    *,
    prompt_version: str,
    prompt_hash: str,
    temperature: float,
    wall: float,
    prompt_tokens: int,
    retry_delay: float,
    status: str = "completed",
    checks_passed: bool | None = True,
) -> dict:
    return {
        "corpus_version": "inventory-corpus-v1",
        "fixture_version": "inventory-fixture-v1",
        "prompt_version": prompt_version,
        "prompt_hash": prompt_hash,
        "provider": {
            "provider": "groq",
            "model": "qwen",
            "config": {"temperature": temperature, "nested": {"x": 1}},
        },
        "cases": [
            {
                "case_id": "find-01",
                "status": status,
                "checks_passed": checks_passed,
                "checks": [{"kind": "item_location", "ok": True}],
                "wall_seconds": wall,
                "turns": [
                    {
                        "rounds": 1,
                        "assistant": f"{prompt_version} answer",
                        "tool_trace": [
                            {
                                "assistant": {
                                    "metadata": {
                                        "usage": {
                                            "prompt_tokens": prompt_tokens,
                                            "completion_tokens": 7,
                                            "total_tokens": prompt_tokens + 7,
                                        },
                                        "provider_server_seconds": 0.2,
                                        "transport": {
                                            "client_wall_seconds": 0.4,
                                            "retry_events": [
                                                {
                                                    "kind": "http",
                                                    "status": 429,
                                                    "delay_seconds": retry_delay,
                                                }
                                            ],
                                        },
                                    },
                                    "tool_calls": [
                                        {
                                            "id": "1",
                                            "name": "search_items",
                                            "arguments": {"query": "x"},
                                        }
                                    ],
                                },
                                "tool_results": [
                                    {
                                        "result": {
                                            "ok": False,
                                            "error": {"type": "test"},
                                        }
                                    }
                                ],
                            }
                        ],
                    }
                ],
            }
        ],
    }


def test_compare_reports_is_descriptive_and_has_metric_deltas() -> None:
    baseline = _report(
        prompt_version="inventory-v1",
        prompt_hash="a" * 64,
        temperature=0.0,
        wall=2.0,
        prompt_tokens=100,
        retry_delay=1.5,
    )
    variant = _report(
        prompt_version="inventory-v2-strict",
        prompt_hash="b" * 64,
        temperature=0.6,
        wall=1.25,
        prompt_tokens=80,
        retry_delay=0.0,
    )

    result = compare_reports(baseline, variant)
    case = result["cases"][0]

    assert result["shared_case_count"] == 1
    assert "winner" not in result
    assert "does not rank" in result["note"]
    assert result["baseline"]["llm_config_hash"] != result["variant"]["llm_config_hash"]
    assert result["comparability"] == {
        "same_provider": True,
        "same_model": True,
        "same_provider_config": False,
        "same_case_set": True,
    }
    assert case["baseline"]["prompt_tokens"] == 100
    assert case["baseline"]["retry_delay_seconds"] == 1.5
    assert case["baseline"]["tool_calls"] == {"search_items": 1}
    assert case["baseline"]["tool_errors"] == 1
    assert case["baseline"]["assistant_texts"] == ["inventory-v1 answer"]
    assert case["variant"]["assistant_texts"] == ["inventory-v2-strict answer"]
    assert case["delta_variant_minus_baseline"]["wall_seconds"] == -0.75
    assert case["delta_variant_minus_baseline"]["prompt_tokens"] == -20.0
    assert case["checks_changed"] is False


def test_compare_reports_reports_missing_cases_without_hiding_them() -> None:
    baseline = _report(
        prompt_version="v1",
        prompt_hash="a" * 64,
        temperature=0.0,
        wall=1.0,
        prompt_tokens=10,
        retry_delay=0.0,
    )
    variant = _report(
        prompt_version="v2",
        prompt_hash="b" * 64,
        temperature=0.0,
        wall=1.0,
        prompt_tokens=10,
        retry_delay=0.0,
    )
    variant["cases"][0]["case_id"] = "move-01"

    result = compare_reports(baseline, variant)

    assert result["shared_case_count"] == 0
    assert result["missing_from_variant"] == ["find-01"]
    assert result["missing_from_baseline"] == ["move-01"]


def test_compare_reports_rejects_different_fixtures() -> None:
    baseline = _report(
        prompt_version="v1",
        prompt_hash="a" * 64,
        temperature=0.0,
        wall=1.0,
        prompt_tokens=10,
        retry_delay=0.0,
    )
    variant = _report(
        prompt_version="v2",
        prompt_hash="b" * 64,
        temperature=0.0,
        wall=1.0,
        prompt_tokens=10,
        retry_delay=0.0,
    )
    variant["fixture_version"] = "other-fixture"

    try:
        compare_reports(baseline, variant)
    except ValueError as exc:
        assert "fixture" in str(exc)
    else:
        raise AssertionError("different fixtures must be rejected")
