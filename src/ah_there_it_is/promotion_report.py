"""Build report-only model promotion evidence from benchmark campaigns."""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ah_there_it_is.benchmark_compare import (
    compare_campaigns,
    load_campaign_result,
)


PROMOTION_SCHEMA_VERSION = "promotion-report-v1"
DEFAULT_OUTPUT_DIR = Path("eval/results/promotion-v1")


_HARD_CATEGORY_LABELS = {
    "provider_tool_contract": "provider adapter/tool contract failure",
    "application_checks": "required application scenario/check failure",
    "write_target_safety": "write-target safety failure",
    "mutation_correctness": "mutation correctness failure",
    "quantity_lifecycle_undo": "quantity/removed/Undo invariant failure",
    "unsupported_facts": "unsupported-fact/hallucination check failure",
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _attempts(campaign: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    value = campaign.get("attempts")
    if not isinstance(value, list):
        return []
    return [attempt for attempt in value if isinstance(attempt, Mapping)]


def _declared_attempts(
    campaign: Mapping[str, Any],
) -> tuple[dict[str, tuple[str, str, int]], list[str]]:
    manifest = campaign.get("campaign")
    if not isinstance(manifest, Mapping):
        return {}, ["campaign manifest is missing"]

    live = manifest.get("live_eval")
    probe = manifest.get("model_probe")
    if not isinstance(live, Mapping) or not isinstance(probe, Mapping):
        return {}, ["campaign selections are missing"]

    live_ids = live.get("case_ids")
    probe_ids = probe.get("case_ids")
    repetitions = manifest.get("repetitions")
    if (
        not isinstance(live_ids, list)
        or any(not isinstance(case_id, str) for case_id in live_ids)
        or len(live_ids) != len(set(live_ids))
        or not isinstance(probe_ids, list)
        or any(not isinstance(case_id, str) for case_id in probe_ids)
        or len(probe_ids) != len(set(probe_ids))
        or not isinstance(repetitions, int)
        or isinstance(repetitions, bool)
        or repetitions < 1
    ):
        return {}, ["campaign selections/repetitions are invalid"]

    declared: dict[str, tuple[str, str, int]] = {}
    for case_id in live_ids:
        for repetition in range(1, repetitions + 1):
            slot = f"live_eval:{case_id}:{repetition}"
            declared[slot] = ("live_eval", case_id, repetition)
    for case_id in probe_ids:
        slot = f"model_probe:{case_id}:1"
        declared[slot] = ("model_probe", case_id, 1)
    return declared, []


def _valid_attempt_evidence(
    attempt: Mapping[str, Any],
    *,
    pipeline: str,
    case_id: str,
) -> bool:
    evidence = attempt.get("evidence")
    if not isinstance(evidence, Mapping):
        return False
    execution_error = evidence.get("campaign_execution_error")
    if execution_error is not None:
        return (
            isinstance(execution_error, Mapping)
            and isinstance(execution_error.get("type"), str)
            and bool(execution_error.get("type"))
            and isinstance(execution_error.get("message"), str)
        )
    if pipeline == "live_eval":
        return (
            evidence.get("case_id") == case_id
            and evidence.get("status") in {"completed", "failed"}
            and isinstance(evidence.get("checks_passed"), bool)
            and isinstance(evidence.get("checks"), list)
        )
    if pipeline == "model_probe":
        return evidence.get("case_id") == case_id and isinstance(evidence.get("passed"), bool)
    return False


def campaign_evidence_completeness(campaign: Mapping[str, Any]) -> dict[str, Any]:
    """Check that persisted attempts exactly and validly cover declared slots."""

    declared, declaration_errors = _declared_attempts(campaign)
    expected = list(declared)
    raw_attempts = campaign.get("attempts")
    attempts = _attempts(campaign)
    observed: list[str] = []
    incomplete: list[str] = []
    invalid_attempt_refs: list[str] = []
    invalid_attempt_count = (
        sum(1 for attempt in raw_attempts if not isinstance(attempt, Mapping))
        if isinstance(raw_attempts, list)
        else 0
    )
    for attempt in attempts:
        slot_id = attempt.get("slot_id")
        if not isinstance(slot_id, str):
            invalid_attempt_count += 1
            continue
        observed.append(slot_id)
        expected_attempt = declared.get(slot_id)
        if attempt.get("completed") is not True:
            incomplete.append(slot_id)
        if expected_attempt is None:
            continue
        pipeline, case_id, repetition = expected_attempt
        if (
            attempt.get("pipeline") != pipeline
            or attempt.get("case_id") != case_id
            or attempt.get("repetition") != repetition
            or not _valid_attempt_evidence(attempt, pipeline=pipeline, case_id=case_id)
        ):
            invalid_attempt_refs.append(slot_id)

    expected_set = set(expected)
    observed_set = set(observed)
    duplicate_slots = sorted({slot for slot in observed if observed.count(slot) > 1})
    missing = sorted(expected_set - observed_set)
    unexpected = sorted(observed_set - expected_set)
    reasons = list(declaration_errors)
    if campaign.get("schema_version") != "benchmark-result-v1":
        reasons.append("campaign result schema is not benchmark-result-v1")
    if campaign.get("completed") is not True:
        reasons.append("campaign result is not marked completed")
    if missing:
        reasons.append("declared attempt slots are missing")
    if unexpected:
        reasons.append("unexpected attempt slots are present")
    if incomplete:
        reasons.append("attempt slots are not marked completed")
    if duplicate_slots:
        reasons.append("duplicate attempt slots are present")
    if invalid_attempt_refs:
        reasons.append("attempt metadata/evidence does not match declared slots")
    if invalid_attempt_count:
        reasons.append("attempts without valid slot_id are present")

    return {
        "complete": not reasons,
        "expected_attempt_count": len(expected),
        "observed_attempt_count": len(observed),
        "missing_attempt_refs": missing,
        "unexpected_attempt_refs": unexpected,
        "incomplete_attempt_refs": sorted(incomplete),
        "duplicate_attempt_refs": duplicate_slots,
        "invalid_attempt_refs": sorted(set(invalid_attempt_refs)),
        "invalid_attempt_count": invalid_attempt_count,
        "reasons": reasons,
        "expected_attempt_refs": expected,
    }


def _evaluation_identity(campaign: Mapping[str, Any]) -> dict[str, Any]:
    provider = campaign.get("provider")
    provider = provider if isinstance(provider, Mapping) else {}
    return {
        "provider": provider.get("provider"),
        "model": provider.get("model"),
        "config_label": provider.get("config_label"),
        "config_hash": provider.get("config_hash"),
        "config": dict(provider.get("config"))
        if isinstance(provider.get("config"), Mapping)
        else {},
        "prompt_version": campaign.get("prompt_version"),
        "prompt_hash": campaign.get("prompt_hash"),
        "corpus_version": campaign.get("corpus_version"),
        "corpus_hash": campaign.get("corpus_hash"),
        "probe_suite_version": campaign.get("probe_suite_version"),
        "probe_suite_hash": campaign.get("probe_suite_hash"),
        "execution_identity_hash": campaign.get("execution_identity_hash"),
    }


def _hard_gate_reasons(
    comparison: Mapping[str, Any],
    baseline_completeness: Mapping[str, Any],
    candidate_completeness: Mapping[str, Any],
) -> list[dict[str, Any]]:
    reasons: list[dict[str, Any]] = []
    if not baseline_completeness.get("complete"):
        reasons.append(
            {
                "gate": "evidence_completeness",
                "side": "baseline",
                "reason": "baseline campaign evidence is incomplete",
                "details": list(baseline_completeness.get("reasons") or []),
                "attempt_refs": sorted(
                    set(baseline_completeness.get("missing_attempt_refs") or [])
                    | set(baseline_completeness.get("incomplete_attempt_refs") or [])
                    | set(baseline_completeness.get("unexpected_attempt_refs") or [])
                    | set(baseline_completeness.get("duplicate_attempt_refs") or [])
                    | set(baseline_completeness.get("invalid_attempt_refs") or [])
                ),
            }
        )
    if not candidate_completeness.get("complete"):
        reasons.append(
            {
                "gate": "evidence_completeness",
                "side": "candidate",
                "reason": "candidate campaign evidence is incomplete",
                "details": list(candidate_completeness.get("reasons") or []),
                "attempt_refs": sorted(
                    set(candidate_completeness.get("missing_attempt_refs") or [])
                    | set(candidate_completeness.get("incomplete_attempt_refs") or [])
                    | set(candidate_completeness.get("unexpected_attempt_refs") or [])
                    | set(candidate_completeness.get("duplicate_attempt_refs") or [])
                    | set(candidate_completeness.get("invalid_attempt_refs") or [])
                ),
            }
        )

    candidate_hard = (
        comparison.get("candidate", {}).get("hard_correctness", {}).get("categories", {})
        if isinstance(comparison.get("candidate"), Mapping)
        else {}
    )
    if isinstance(candidate_hard, Mapping):
        for category, label in _HARD_CATEGORY_LABELS.items():
            value = candidate_hard.get(category)
            if not isinstance(value, Mapping):
                continue
            failure_count = value.get("failure_count")
            if isinstance(failure_count, int) and failure_count > 0:
                reasons.append(
                    {
                        "gate": category,
                        "side": "candidate",
                        "reason": label,
                        "failure_count": failure_count,
                        "attempt_refs": list(value.get("attempt_refs") or []),
                    }
                )
    return reasons


def _metric_observations(comparison: Mapping[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    regressions: list[dict[str, Any]] = []
    improvements: list[dict[str, Any]] = []

    hard_gate = comparison.get("hard_gate")
    if isinstance(hard_gate, Mapping):
        for regression in hard_gate.get("hard_regressions") or []:
            if isinstance(regression, Mapping):
                regressions.append(
                    {
                        "area": "hard_correctness",
                        "metric": regression.get("category"),
                        "delta": regression.get("failure_count_delta"),
                        "candidate_attempt_refs": list(
                            regression.get("candidate_attempt_refs") or []
                        ),
                    }
                )

    deltas = comparison.get("deltas")
    if not isinstance(deltas, Mapping):
        return regressions, improvements

    behavior = deltas.get("behavior_candidate_minus_baseline")
    if isinstance(behavior, Mapping):
        for metric in ("passed_attempts",):
            delta = behavior.get(metric)
            if isinstance(delta, (int, float)) and not isinstance(delta, bool) and delta:
                target = improvements if delta > 0 else regressions
                target.append({"area": "behavior", "metric": metric, "delta": delta})
        for metric in ("failed_attempts", "rounds", "tool_calls", "clarification_count"):
            delta = behavior.get(metric)
            if isinstance(delta, (int, float)) and not isinstance(delta, bool) and delta:
                target = improvements if delta < 0 else regressions
                target.append({"area": "behavior", "metric": metric, "delta": delta})

    repeatability = deltas.get("repeatability_candidate_minus_baseline")
    if isinstance(repeatability, Mapping):
        for metric in ("disagreement_rate", "intermittent_failure_rate"):
            delta = repeatability.get(metric)
            if isinstance(delta, (int, float)) and not isinstance(delta, bool) and delta:
                target = improvements if delta < 0 else regressions
                target.append({"area": "repeatability", "metric": metric, "delta": delta})

    operations = deltas.get("operations_candidate_minus_baseline")
    if isinstance(operations, Mapping):
        for metric in (
            "wall_seconds_total",
            "wall_seconds_mean",
            "provider_error_count",
            "rate_limit_events",
            "total_tokens",
            "cost_usd",
        ):
            delta = operations.get(metric)
            if isinstance(delta, (int, float)) and not isinstance(delta, bool) and delta:
                target = improvements if delta < 0 else regressions
                target.append({"area": "operations", "metric": metric, "delta": delta})

    return regressions, improvements


def build_promotion_report(
    baseline: Mapping[str, Any],
    candidate: Mapping[str, Any],
    *,
    baseline_evidence_file: str | None = None,
    candidate_evidence_file: str | None = None,
    comparison_evidence_file: str | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Build a reproducible report. This function never mutates runtime configuration."""

    timestamp = generated_at or _utc_now()
    comparison = compare_campaigns(baseline, candidate, generated_at=timestamp)
    baseline_completeness = campaign_evidence_completeness(baseline)
    candidate_completeness = campaign_evidence_completeness(candidate)
    hard_reasons = _hard_gate_reasons(
        comparison, baseline_completeness, candidate_completeness
    )
    regressions, improvements = _metric_observations(comparison)

    return {
        "schema_version": PROMOTION_SCHEMA_VERSION,
        "generated_at": timestamp,
        "promotion_mode": "manual",
        "hard_gate_passed": not hard_reasons,
        "hard_gate_reasons": hard_reasons,
        "baseline": _evaluation_identity(baseline),
        "candidate": _evaluation_identity(candidate),
        "evaluation_versions": {
            "prompt_version": candidate.get("prompt_version"),
            "prompt_hash": candidate.get("prompt_hash"),
            "corpus_version": candidate.get("corpus_version"),
            "corpus_hash": candidate.get("corpus_hash"),
            "probe_suite_version": candidate.get("probe_suite_version"),
            "probe_suite_hash": candidate.get("probe_suite_hash"),
        },
        "evidence_completeness": {
            "baseline": baseline_completeness,
            "candidate": candidate_completeness,
        },
        "behavioral_comparison": comparison.get("deltas", {}).get(
            "behavior_candidate_minus_baseline"
        ),
        "repeatability_comparison": comparison.get("deltas", {}).get(
            "repeatability_candidate_minus_baseline"
        ),
        "operational_comparison": comparison.get("deltas", {}).get(
            "operations_candidate_minus_baseline"
        ),
        "intermittent_failures": {
            "baseline": comparison["baseline"]["repeatability"][
                "intermittent_failure_attempt_refs"
            ],
            "candidate": comparison["candidate"]["repeatability"][
                "intermittent_failure_attempt_refs"
            ],
        },
        "known_regressions": regressions,
        "known_improvements": improvements,
        "evidence_files": {
            "baseline_campaign": baseline_evidence_file,
            "candidate_campaign": candidate_evidence_file,
            "comparison": comparison_evidence_file,
        },
        "comparison": comparison,
        "note": (
            "Report-only evidence. Promotion remains a manual decision; this report "
            "does not edit provider/model configuration. Cost and latency are observations, "
            "not correctness gates."
        ),
    }


def render_promotion_markdown(report: Mapping[str, Any]) -> str:
    baseline = report.get("baseline") or {}
    candidate = report.get("candidate") or {}
    lines = [
        "# Model promotion evidence",
        "",
        f"- Schema: `{report.get('schema_version')}`",
        f"- Generated: `{report.get('generated_at')}`",
        f"- Promotion mode: `{report.get('promotion_mode')}`",
        f"- Baseline: `{baseline.get('provider')}/{baseline.get('model')}` (`{baseline.get('config_label')}`)",
        f"- Candidate: `{candidate.get('provider')}/{candidate.get('model')}` (`{candidate.get('config_label')}`)",
        f"- Hard gate passed: `{str(bool(report.get('hard_gate_passed'))).lower()}`",
        "",
        "## Hard gates",
        "",
    ]
    reasons = report.get("hard_gate_reasons") or []
    if reasons:
        for reason in reasons:
            refs = reason.get("attempt_refs") or []
            suffix = "" if not refs else "; evidence: " + ", ".join(f"`{ref}`" for ref in refs)
            lines.append(f"- {reason.get('reason')}{suffix}")
    else:
        lines.append("- No correctness/evidence-completeness gate failures observed.")

    completeness = report.get("evidence_completeness") or {}
    lines.extend(["", "## Evidence completeness", ""])
    for side in ("baseline", "candidate"):
        value = completeness.get(side) or {}
        lines.append(
            f"- {side}: complete=`{str(bool(value.get('complete'))).lower()}`, "
            f"expected={value.get('expected_attempt_count')}, observed={value.get('observed_attempt_count')}"
        )

    lines.extend(["", "## Known regressions", ""])
    regressions = report.get("known_regressions") or []
    lines.extend(
        f"- {item.get('area')}.{item.get('metric')}: delta {item.get('delta')}"
        for item in regressions
    )
    if not regressions:
        lines.append("- None recorded.")

    lines.extend(["", "## Known improvements", ""])
    improvements = report.get("known_improvements") or []
    lines.extend(
        f"- {item.get('area')}.{item.get('metric')}: delta {item.get('delta')}"
        for item in improvements
    )
    if not improvements:
        lines.append("- None recorded.")

    lines.extend(["", "## Evidence files", ""])
    for name, value in (report.get("evidence_files") or {}).items():
        lines.append(f"- {name}: `{value if value is not None else 'not supplied'}`")
    lines.extend(["", str(report.get("note") or ""), ""])
    return "\n".join(lines)


def write_promotion_reports(
    report: Mapping[str, Any],
    *,
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
    file_prefix: str = "promotion-report",
) -> tuple[Path, Path]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    json_path = output / f"{file_prefix}.json"
    markdown_path = output / f"{file_prefix}.md"
    json_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    markdown_path.write_text(render_promotion_markdown(report), encoding="utf-8")
    return json_path, markdown_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("baseline")
    parser.add_argument("candidate")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--file-prefix", default="promotion-report")
    parser.add_argument("--comparison-evidence")
    args = parser.parse_args()

    baseline = load_campaign_result(args.baseline)
    candidate = load_campaign_result(args.candidate)
    report = build_promotion_report(
        baseline,
        candidate,
        baseline_evidence_file=args.baseline,
        candidate_evidence_file=args.candidate,
        comparison_evidence_file=args.comparison_evidence,
    )
    json_path, markdown_path = write_promotion_reports(
        report, output_dir=args.output_dir, file_prefix=args.file_prefix
    )
    print(json.dumps({"json": str(json_path), "markdown": str(markdown_path), "hard_gate_passed": report["hard_gate_passed"]}))


if __name__ == "__main__":
    main()
