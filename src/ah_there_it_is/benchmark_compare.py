"""Aggregate benchmark campaigns and compare baseline/candidate evidence."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any, Mapping


COMPARISON_SCHEMA_VERSION = "benchmark-comparison-v1"

_MUTATION_CHECK_KINDS = {
    "event_count_delta",
    "item_event",
    "item_location",
    "item_location_none",
    "item_location_status",
    "item_state",
    "item_quantity",
    "item_quantity_truth",
    "item_description_contains",
    "item_history_min_events",
    "item_attribute_equals",
    "item_category_none",
    "item_exists",
}
_QUANTITY_CHECK_KINDS = {"item_quantity", "item_quantity_truth"}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def load_campaign_result(path: str | Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if value.get("schema_version") != "benchmark-result-v1":
        raise ValueError("unsupported benchmark campaign result schema")
    return value


def _attempts(campaign: Mapping[str, Any]) -> list[dict[str, Any]]:
    raw = campaign.get("attempts")
    if not isinstance(raw, list):
        raise ValueError("campaign attempts must be a list")
    if any(not isinstance(attempt, dict) for attempt in raw):
        raise ValueError("every benchmark attempt must be an object")
    attempts = list(raw)
    slot_ids = [attempt.get("slot_id") for attempt in attempts]
    if any(not isinstance(slot, str) for slot in slot_ids):
        raise ValueError("every benchmark attempt must have a slot_id")
    if len(slot_ids) != len(set(slot_ids)):
        raise ValueError("benchmark attempt slot_ids must be unique")
    return attempts


def _identity(campaign: Mapping[str, Any]) -> dict[str, Any]:
    provider = campaign.get("provider")
    provider = provider if isinstance(provider, dict) else {}
    manifest = campaign.get("campaign")
    manifest = manifest if isinstance(manifest, dict) else {}
    live = manifest.get("live_eval")
    live = live if isinstance(live, dict) else {}
    probe = manifest.get("model_probe")
    probe = probe if isinstance(probe, dict) else {}
    return {
        "campaign_id": manifest.get("campaign_id"),
        "campaign_version": manifest.get("campaign_version"),
        "live_case_ids": (
            list(live.get("case_ids"))
            if isinstance(live.get("case_ids"), list)
            else None
        ),
        "probe_case_ids": (
            list(probe.get("case_ids"))
            if isinstance(probe.get("case_ids"), list)
            else None
        ),
        "repetitions": manifest.get("repetitions"),
        "provider": provider.get("provider"),
        "model": provider.get("model"),
        "config_label": provider.get("config_label"),
        "config_hash": provider.get("config_hash"),
        "config": provider.get("config") if isinstance(provider.get("config"), dict) else {},
        "prompt_version": campaign.get("prompt_version"),
        "prompt_hash": campaign.get("prompt_hash"),
        "corpus_version": campaign.get("corpus_version"),
        "corpus_hash": campaign.get("corpus_hash"),
        "probe_suite_version": campaign.get("probe_suite_version"),
        "probe_suite_hash": campaign.get("probe_suite_hash"),
        "execution_identity_hash": campaign.get("execution_identity_hash"),
    }


def _check_failures(evidence: Mapping[str, Any]) -> list[dict[str, Any]]:
    checks = evidence.get("checks")
    if not isinstance(checks, list):
        return []
    return [
        check
        for check in checks
        if isinstance(check, dict) and check.get("ok") is False
    ]


def _provider_error_text(evidence: Mapping[str, Any]) -> str | None:
    campaign_error = evidence.get("campaign_execution_error")
    if isinstance(campaign_error, dict):
        return " ".join(
            str(campaign_error.get(key) or "") for key in ("type", "message")
        ).strip()
    if evidence.get("status") == "failed":
        error = evidence.get("error")
        return str(error) if error else "provider execution failed"
    return None


def _hard_failure_categories(attempt: Mapping[str, Any]) -> set[str]:
    evidence = attempt.get("evidence")
    evidence = evidence if isinstance(evidence, dict) else {}
    pipeline = attempt.get("pipeline")
    categories: set[str] = set()
    provider_error = _provider_error_text(evidence)

    if pipeline == "model_probe":
        if evidence.get("passed") is not True or provider_error:
            categories.add("provider_tool_contract")
        return categories

    if pipeline != "live_eval":
        categories.add("application_checks")
        return categories

    failed_checks = _check_failures(evidence)
    if (
        provider_error
        or evidence.get("status") != "completed"
        or evidence.get("checks_passed") is not True
        or failed_checks
    ):
        categories.add("application_checks")
    for check in failed_checks:
        kind = check.get("kind")
        if kind == "no_mutation":
            categories.add("write_target_safety")
        if kind in _MUTATION_CHECK_KINDS:
            categories.add("mutation_correctness")
        if kind in _QUANTITY_CHECK_KINDS:
            categories.add("quantity_lifecycle_undo")
        detail = check.get("detail")
        if isinstance(detail, dict):
            event_type = detail.get("event_type")
            if event_type in {
                "item_removed",
                "item_restored",
                "item_undo_compensated",
                "item_split",
                "item_quantity_changed",
            }:
                categories.add("quantity_lifecycle_undo")
    case_id = attempt.get("case_id")
    if categories & {"application_checks", "mutation_correctness"} and isinstance(case_id, str):
        if case_id.startswith("quantity-"):
            categories.add("quantity_lifecycle_undo")
    unsupported = evidence.get("unsupported_fact_failures")
    if isinstance(unsupported, int) and unsupported > 0:
        categories.add("unsupported_facts")
    return categories


def _trace_metrics(evidence: Mapping[str, Any]) -> dict[str, Any]:
    turns = evidence.get("turns")
    turns = turns if isinstance(turns, list) else []
    rounds = 0
    tool_calls = 0
    clarification_count = 0
    clarification_observed = False
    prompt_tokens = 0
    completion_tokens = 0
    total_tokens = 0
    cost_usd = 0.0
    token_observed = False
    cost_observed = False
    rate_limit_events = 0

    for turn in turns:
        if not isinstance(turn, dict):
            continue
        if isinstance(turn.get("rounds"), int):
            rounds += turn["rounds"]
        if isinstance(turn.get("clarification"), bool):
            clarification_observed = True
            clarification_count += int(turn["clarification"])
        trace = turn.get("tool_trace")
        if not isinstance(trace, list):
            continue
        for round_trace in trace:
            if not isinstance(round_trace, dict):
                continue
            assistant = round_trace.get("assistant")
            assistant = assistant if isinstance(assistant, dict) else {}
            calls = assistant.get("tool_calls")
            if isinstance(calls, list):
                tool_calls += sum(1 for call in calls if isinstance(call, dict))
            metadata = assistant.get("metadata")
            metadata = metadata if isinstance(metadata, dict) else {}
            usage = metadata.get("usage")
            usage = usage if isinstance(usage, dict) else {}
            prompt_value = next(
                (
                    usage[name]
                    for name in ("prompt_tokens", "promptTokenCount", "input_tokens")
                    if isinstance(usage.get(name), (int, float))
                ),
                None,
            )
            completion_value = next(
                (
                    usage[name]
                    for name in (
                        "completion_tokens",
                        "candidatesTokenCount",
                        "output_tokens",
                    )
                    if isinstance(usage.get(name), (int, float))
                ),
                None,
            )
            total_value = next(
                (
                    usage[name]
                    for name in ("total_tokens", "totalTokenCount")
                    if isinstance(usage.get(name), (int, float))
                ),
                None,
            )
            if any(
                value is not None
                for value in (prompt_value, completion_value, total_value)
            ):
                token_observed = True
                prompt_tokens += int(prompt_value or 0)
                completion_tokens += int(completion_value or 0)
                if total_value is not None:
                    total_tokens += int(total_value)
                else:
                    total_tokens += int(prompt_value or 0) + int(completion_value or 0)
            for key in ("cost_usd", "estimated_cost_usd"):
                value = metadata.get(key)
                if isinstance(value, (int, float)):
                    cost_observed = True
                    cost_usd += float(value)
                    break
            transport = metadata.get("transport")
            transport = transport if isinstance(transport, dict) else {}
            retry_events = transport.get("retry_events")
            if isinstance(retry_events, list):
                for event in retry_events:
                    if not isinstance(event, dict):
                        continue
                    status = event.get("status")
                    kind = str(event.get("kind") or "").casefold()
                    if status == 429 or "rate" in kind:
                        rate_limit_events += 1

    return {
        "rounds": rounds,
        "tool_calls": tool_calls,
        "clarification_count": clarification_count if clarification_observed else None,
        "prompt_tokens": prompt_tokens if token_observed else None,
        "completion_tokens": completion_tokens if token_observed else None,
        "total_tokens": total_tokens if token_observed else None,
        "cost_usd": round(cost_usd, 8) if cost_observed else None,
        "rate_limit_events": rate_limit_events,
    }


def _attempt_passed(attempt: Mapping[str, Any]) -> bool:
    evidence = attempt.get("evidence")
    evidence = evidence if isinstance(evidence, dict) else {}
    if attempt.get("pipeline") == "model_probe":
        return evidence.get("passed") is True and _provider_error_text(evidence) is None
    if attempt.get("pipeline") == "live_eval":
        return evidence.get("status") == "completed" and evidence.get("checks_passed") is True
    return False


def _outcome_fingerprint(attempt: Mapping[str, Any]) -> str:
    evidence = attempt.get("evidence")
    evidence = evidence if isinstance(evidence, dict) else {}
    checks = evidence.get("checks")
    check_outcomes = []
    if isinstance(checks, list):
        check_outcomes = [
            [check.get("kind"), check.get("ok")]
            for check in checks
            if isinstance(check, dict)
        ]
    return json.dumps(
        {
            "passed": _attempt_passed(attempt),
            "status": evidence.get("status"),
            "probe_passed": evidence.get("passed"),
            "checks": check_outcomes,
            "provider_error": bool(_provider_error_text(evidence)),
        },
        sort_keys=True,
        separators=(",", ":"),
    )


def aggregate_campaign(campaign: Mapping[str, Any]) -> dict[str, Any]:
    attempts = _attempts(campaign)
    refs_by_hard_category: dict[str, list[str]] = defaultdict(list)
    completed_refs: list[str] = []
    passed_refs: list[str] = []
    failed_refs: list[str] = []
    provider_error_refs: list[str] = []
    wall_values: list[float] = []
    wall_refs: list[str] = []
    trace_metrics = []

    repeated: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for attempt in attempts:
        slot_id = str(attempt["slot_id"])
        if attempt.get("completed") is True:
            completed_refs.append(slot_id)
        if _attempt_passed(attempt):
            passed_refs.append(slot_id)
        else:
            failed_refs.append(slot_id)
        for category in _hard_failure_categories(attempt):
            refs_by_hard_category[category].append(slot_id)
        evidence = attempt.get("evidence")
        evidence = evidence if isinstance(evidence, dict) else {}
        if _provider_error_text(evidence):
            provider_error_refs.append(slot_id)
        wall = evidence.get("wall_seconds")
        if isinstance(wall, (int, float)):
            wall_values.append(float(wall))
            wall_refs.append(slot_id)
        trace_metrics.append((slot_id, _trace_metrics(evidence)))
        pipeline = str(attempt.get("pipeline") or "")
        case_id = str(attempt.get("case_id") or "")
        repeated[(pipeline, case_id)].append(attempt)

    repeat_cases = []
    disagreement_refs: list[str] = []
    intermittent_refs: list[str] = []
    repeated_groups = 0
    for (pipeline, case_id), group in sorted(repeated.items()):
        if len(group) < 2:
            continue
        repeated_groups += 1
        fingerprints = {_outcome_fingerprint(attempt) for attempt in group}
        pass_states = {_attempt_passed(attempt) for attempt in group}
        refs = [str(attempt["slot_id"]) for attempt in group]
        disagreed = len(fingerprints) > 1
        intermittent = pass_states == {False, True}
        if disagreed:
            disagreement_refs.extend(refs)
        if intermittent:
            intermittent_refs.extend(refs)
        repeat_cases.append(
            {
                "pipeline": pipeline,
                "case_id": case_id,
                "attempt_refs": refs,
                "disagreement": disagreed,
                "intermittent_failure": intermittent,
            }
        )

    hard_categories = (
        "provider_tool_contract",
        "application_checks",
        "write_target_safety",
        "mutation_correctness",
        "quantity_lifecycle_undo",
        "unsupported_facts",
    )
    hard = {
        category: {
            "failure_count": len(refs_by_hard_category.get(category, [])),
            "attempt_refs": sorted(refs_by_hard_category.get(category, [])),
        }
        for category in hard_categories
    }
    hard_failure_refs = sorted(
        {ref for category in hard.values() for ref in category["attempt_refs"]}
    )

    rounds_total = sum(metrics["rounds"] for _, metrics in trace_metrics)
    tool_calls_total = sum(metrics["tool_calls"] for _, metrics in trace_metrics)
    rounds_refs = [slot for slot, metrics in trace_metrics if metrics["rounds"]]
    tool_call_refs = [slot for slot, metrics in trace_metrics if metrics["tool_calls"]]
    clarification_refs = [
        slot for slot, metrics in trace_metrics if metrics["clarification_count"] is not None
    ]
    clarification_values = [
        metrics["clarification_count"]
        for _, metrics in trace_metrics
        if metrics["clarification_count"] is not None
    ]
    prompt_tokens = [m["prompt_tokens"] for _, m in trace_metrics if m["prompt_tokens"] is not None]
    completion_tokens = [m["completion_tokens"] for _, m in trace_metrics if m["completion_tokens"] is not None]
    total_tokens = [m["total_tokens"] for _, m in trace_metrics if m["total_tokens"] is not None]
    costs = [m["cost_usd"] for _, m in trace_metrics if m["cost_usd"] is not None]
    token_refs = [
        slot
        for slot, metrics in trace_metrics
        if any(metrics[key] is not None for key in ("prompt_tokens", "completion_tokens", "total_tokens"))
    ]
    cost_refs = [slot for slot, metrics in trace_metrics if metrics["cost_usd"] is not None]
    rate_limit_refs = [slot for slot, metrics in trace_metrics if metrics["rate_limit_events"]]
    rate_limit_events = sum(m["rate_limit_events"] for _, m in trace_metrics)

    return {
        "identity": _identity(campaign),
        "hard_correctness": {
            "passed": not hard_failure_refs,
            "failure_attempt_refs": hard_failure_refs,
            "categories": hard,
        },
        "behavior": {
            "attempt_count": len(attempts),
            "completed_attempts": len(completed_refs),
            "passed_attempts": len(passed_refs),
            "failed_attempts": len(failed_refs),
            "rounds": rounds_total,
            "tool_calls": tool_calls_total,
            "clarification_count": sum(clarification_values) if clarification_values else None,
            "attempt_refs": {
                "completed": completed_refs,
                "passed": passed_refs,
                "failed": failed_refs,
                "rounds": rounds_refs,
                "tool_calls": tool_call_refs,
                "clarifications": clarification_refs,
            },
        },
        "repeatability": {
            "repeated_case_count": repeated_groups,
            "disagreement_case_count": sum(case["disagreement"] for case in repeat_cases),
            "intermittent_failure_case_count": sum(
                case["intermittent_failure"] for case in repeat_cases
            ),
            "disagreement_rate": (
                sum(case["disagreement"] for case in repeat_cases) / repeated_groups
                if repeated_groups
                else 0.0
            ),
            "intermittent_failure_rate": (
                sum(case["intermittent_failure"] for case in repeat_cases) / repeated_groups
                if repeated_groups
                else 0.0
            ),
            "disagreement_attempt_refs": sorted(set(disagreement_refs)),
            "intermittent_failure_attempt_refs": sorted(set(intermittent_refs)),
            "cases": repeat_cases,
        },
        "operations": {
            "wall_seconds_total": round(sum(wall_values), 6),
            "wall_seconds_mean": round(mean(wall_values), 6) if wall_values else None,
            "provider_error_count": len(provider_error_refs),
            "provider_error_attempt_refs": provider_error_refs,
            "rate_limit_events": rate_limit_events,
            "prompt_tokens": sum(prompt_tokens) if prompt_tokens else None,
            "completion_tokens": sum(completion_tokens) if completion_tokens else None,
            "total_tokens": sum(total_tokens) if total_tokens else None,
            "cost_usd": round(sum(costs), 8) if costs else None,
            "token_data_available": bool(total_tokens or prompt_tokens or completion_tokens),
            "cost_data_available": bool(costs),
            "attempt_refs": {
                "wall_seconds": wall_refs,
                "provider_errors": provider_error_refs,
                "rate_limits": rate_limit_refs,
                "tokens": token_refs,
                "cost": cost_refs,
            },
        },
        "all_attempt_refs": [str(attempt["slot_id"]) for attempt in attempts],
    }


def _numeric_delta(candidate: Any, baseline: Any) -> float | int | None:
    if not isinstance(candidate, (int, float)) or isinstance(candidate, bool):
        return None
    if not isinstance(baseline, (int, float)) or isinstance(baseline, bool):
        return None
    value = candidate - baseline
    return round(value, 8) if isinstance(value, float) else value


def compare_campaigns(
    baseline: Mapping[str, Any],
    candidate: Mapping[str, Any],
    *,
    generated_at: str | None = None,
) -> dict[str, Any]:
    baseline_agg = aggregate_campaign(baseline)
    candidate_agg = aggregate_campaign(candidate)
    b_id = baseline_agg["identity"]
    c_id = candidate_agg["identity"]
    for field in (
        "prompt_version",
        "prompt_hash",
        "corpus_version",
        "corpus_hash",
        "probe_suite_version",
        "probe_suite_hash",
        "live_case_ids",
        "probe_case_ids",
        "repetitions",
    ):
        baseline_value = b_id.get(field)
        candidate_value = c_id.get(field)
        if baseline_value is None or candidate_value is None:
            raise ValueError(f"campaigns are not comparable: {field} is missing")
        if baseline_value != candidate_value:
            raise ValueError(f"campaigns are not comparable: {field} differs")

    hard_regressions = []
    for category, candidate_value in candidate_agg["hard_correctness"]["categories"].items():
        baseline_value = baseline_agg["hard_correctness"]["categories"][category]
        delta = candidate_value["failure_count"] - baseline_value["failure_count"]
        if delta > 0:
            hard_regressions.append(
                {
                    "category": category,
                    "failure_count_delta": delta,
                    "baseline_attempt_refs": baseline_value["attempt_refs"],
                    "candidate_attempt_refs": candidate_value["attempt_refs"],
                }
            )

    behavior_fields = ("completed_attempts", "passed_attempts", "failed_attempts", "rounds", "tool_calls", "clarification_count")
    operational_fields = (
        "wall_seconds_total",
        "wall_seconds_mean",
        "provider_error_count",
        "rate_limit_events",
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
        "cost_usd",
    )
    behavior_delta = {
        field: _numeric_delta(candidate_agg["behavior"].get(field), baseline_agg["behavior"].get(field))
        for field in behavior_fields
    }
    operations_delta = {
        field: _numeric_delta(candidate_agg["operations"].get(field), baseline_agg["operations"].get(field))
        for field in operational_fields
    }
    repeatability_delta = {
        field: _numeric_delta(candidate_agg["repeatability"].get(field), baseline_agg["repeatability"].get(field))
        for field in ("disagreement_rate", "intermittent_failure_rate", "disagreement_case_count", "intermittent_failure_case_count")
    }

    return {
        "schema_version": COMPARISON_SCHEMA_VERSION,
        "generated_at": generated_at or _utc_now(),
        "baseline": baseline_agg,
        "candidate": candidate_agg,
        "hard_gate": {
            "passed": not hard_regressions and candidate_agg["hard_correctness"]["passed"],
            "hard_regressions": hard_regressions,
            "candidate_has_hard_failures": not candidate_agg["hard_correctness"]["passed"],
        },
        "deltas": {
            "behavior_candidate_minus_baseline": behavior_delta,
            "repeatability_candidate_minus_baseline": repeatability_delta,
            "operations_candidate_minus_baseline": operations_delta,
        },
        "note": "Hard correctness, behavior, repeatability, and operations are reported separately; no overall score or automatic selection is produced.",
    }


def render_comparison_markdown(comparison: Mapping[str, Any]) -> str:
    baseline = comparison["baseline"]
    candidate = comparison["candidate"]
    gate = comparison["hard_gate"]
    lines = [
        "# Benchmark comparison",
        "",
        f"- Schema: `{comparison['schema_version']}`",
        f"- Generated: `{comparison['generated_at']}`",
        f"- Baseline: `{baseline['identity']['provider']}/{baseline['identity']['model']}` (`{baseline['identity']['config_label']}`)",
        f"- Candidate: `{candidate['identity']['provider']}/{candidate['identity']['model']}` (`{candidate['identity']['config_label']}`)",
        f"- Hard gate passed: `{str(gate['passed']).lower()}`",
        "",
        "## Hard correctness",
        "",
    ]
    for category in candidate["hard_correctness"]["categories"]:
        b = baseline["hard_correctness"]["categories"][category]["failure_count"]
        c = candidate["hard_correctness"]["categories"][category]["failure_count"]
        lines.append(f"- {category}: baseline {b}, candidate {c}")
    if gate["hard_regressions"]:
        lines.extend(["", "Hard regressions:"])
        for regression in gate["hard_regressions"]:
            lines.append(
                f"- {regression['category']}: +{regression['failure_count_delta']} failures; candidate evidence "
                + ", ".join(f"`{ref}`" for ref in regression["candidate_attempt_refs"])
            )
    lines.extend(
        [
            "",
            "## Behavior / repeatability",
            "",
            f"- Candidate passed attempts: {candidate['behavior']['passed_attempts']} / {candidate['behavior']['attempt_count']}",
            f"- Candidate disagreement rate: {candidate['repeatability']['disagreement_rate']:.3f}",
            f"- Candidate intermittent-failure rate: {candidate['repeatability']['intermittent_failure_rate']:.3f}",
            "",
            "## Operations",
            "",
            f"- Candidate wall time total: {candidate['operations']['wall_seconds_total']}",
            f"- Candidate provider errors: {candidate['operations']['provider_error_count']}",
            f"- Candidate token data: {candidate['operations']['total_tokens'] if candidate['operations']['token_data_available'] else 'unavailable'}",
            f"- Candidate cost USD: {candidate['operations']['cost_usd'] if candidate['operations']['cost_data_available'] else 'unavailable'}",
            "",
            comparison["note"],
            "",
        ]
    )
    return "\n".join(lines)


def write_comparison_reports(
    comparison: Mapping[str, Any],
    *,
    json_path: str | Path,
    markdown_path: str | Path,
) -> None:
    json_output = Path(json_path)
    markdown_output = Path(markdown_path)
    json_output.parent.mkdir(parents=True, exist_ok=True)
    markdown_output.parent.mkdir(parents=True, exist_ok=True)
    json_output.write_text(json.dumps(comparison, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    markdown_output.write_text(render_comparison_markdown(comparison), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("baseline")
    parser.add_argument("candidate")
    parser.add_argument("--json-output", required=True)
    parser.add_argument("--markdown-output", required=True)
    args = parser.parse_args()
    comparison = compare_campaigns(
        load_campaign_result(args.baseline), load_campaign_result(args.candidate)
    )
    write_comparison_reports(
        comparison, json_path=args.json_output, markdown_path=args.markdown_output
    )


if __name__ == "__main__":
    main()
