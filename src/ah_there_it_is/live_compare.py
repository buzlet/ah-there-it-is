"""Compare two live-evaluation JSON reports without choosing a winner."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any


def _canonical_config(config: Any) -> tuple[dict[str, Any], str]:
    value = config if isinstance(config, dict) else {}
    canonical = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return value, hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _identity(report: dict[str, Any]) -> dict[str, Any]:
    provider = report.get("provider")
    provider = provider if isinstance(provider, dict) else {}
    config, config_hash = _canonical_config(provider.get("config"))
    return {
        "corpus_version": report.get("corpus_version"),
        "fixture_version": report.get("fixture_version"),
        "prompt_version": report.get("prompt_version"),
        "prompt_hash": report.get("prompt_hash"),
        "llm_provider": provider.get("provider"),
        "llm_model": provider.get("model"),
        "llm_config_hash": config_hash,
        "llm_config": config,
    }


def _usage_number(usage: dict[str, Any], *names: str) -> int:
    for name in names:
        value = usage.get(name)
        if isinstance(value, (int, float)):
            return int(value)
    return 0


def _case_metrics(case: dict[str, Any]) -> dict[str, Any]:
    prompt_tokens = 0
    completion_tokens = 0
    total_tokens = 0
    retry_delay_seconds = 0.0
    provider_server_seconds = 0.0
    client_wall_seconds = 0.0
    tool_calls: Counter[str] = Counter()
    tool_errors = 0
    assistant_texts: list[str] = []
    response_models: set[str] = set()
    system_fingerprints: set[str] = set()

    turns = case.get("turns")
    if not isinstance(turns, list):
        turns = []
    for turn in turns:
        if not isinstance(turn, dict):
            continue
        assistant_text = turn.get("assistant")
        if isinstance(assistant_text, str):
            assistant_texts.append(assistant_text)
        trace = turn.get("tool_trace")
        if not isinstance(trace, list):
            continue
        for round_trace in trace:
            if not isinstance(round_trace, dict):
                continue
            assistant = round_trace.get("assistant")
            assistant = assistant if isinstance(assistant, dict) else {}
            metadata = assistant.get("metadata")
            metadata = metadata if isinstance(metadata, dict) else {}
            response_model = metadata.get("response_model")
            if isinstance(response_model, str) and response_model:
                response_models.add(response_model)
            system_fingerprint = metadata.get("system_fingerprint")
            if isinstance(system_fingerprint, str) and system_fingerprint:
                system_fingerprints.add(system_fingerprint)
            usage = metadata.get("usage")
            usage = usage if isinstance(usage, dict) else {}
            prompt_tokens += _usage_number(
                usage,
                "prompt_tokens",
                "promptTokenCount",
                "input_tokens",
            )
            completion_tokens += _usage_number(
                usage,
                "completion_tokens",
                "candidatesTokenCount",
                "output_tokens",
            )
            total_tokens += _usage_number(
                usage,
                "total_tokens",
                "totalTokenCount",
            )
            provider_time = metadata.get("provider_server_seconds")
            if isinstance(provider_time, (int, float)):
                provider_server_seconds += float(provider_time)
            transport = metadata.get("transport")
            transport = transport if isinstance(transport, dict) else {}
            wall = transport.get("client_wall_seconds")
            if isinstance(wall, (int, float)):
                client_wall_seconds += float(wall)
            retry_events = transport.get("retry_events")
            if isinstance(retry_events, list):
                for event in retry_events:
                    if not isinstance(event, dict):
                        continue
                    delay = event.get("delay_seconds")
                    if isinstance(delay, (int, float)):
                        retry_delay_seconds += float(delay)

            calls = assistant.get("tool_calls")
            if isinstance(calls, list):
                for call in calls:
                    if isinstance(call, dict) and isinstance(call.get("name"), str):
                        tool_calls[call["name"]] += 1

            results = round_trace.get("tool_results")
            if isinstance(results, list):
                for result_entry in results:
                    if not isinstance(result_entry, dict):
                        continue
                    result = result_entry.get("result")
                    if isinstance(result, dict) and result.get("ok") is False:
                        tool_errors += 1

    rounds = sum(
        int(turn.get("rounds") or 0)
        for turn in turns
        if isinstance(turn, dict)
    )
    if not total_tokens:
        total_tokens = prompt_tokens + completion_tokens
    checks = case.get("checks")
    checks = checks if isinstance(checks, list) else []
    return {
        "status": case.get("status"),
        "error": case.get("error"),
        "checks_passed": case.get("checks_passed"),
        "checks_count": len(checks),
        "rounds": rounds,
        "wall_seconds": float(case.get("wall_seconds") or 0.0),
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
        "client_wall_seconds": round(client_wall_seconds, 6),
        "provider_server_seconds": round(provider_server_seconds, 6),
        "retry_delay_seconds": round(retry_delay_seconds, 6),
        "tool_calls": dict(sorted(tool_calls.items())),
        "tool_call_count": sum(tool_calls.values()),
        "tool_errors": tool_errors,
        "assistant_texts": assistant_texts,
        "response_models": sorted(response_models),
        "system_fingerprints": sorted(system_fingerprints),
    }


def _delta(baseline: dict[str, Any], variant: dict[str, Any]) -> dict[str, Any]:
    fields = (
        "rounds",
        "wall_seconds",
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
        "client_wall_seconds",
        "provider_server_seconds",
        "retry_delay_seconds",
        "tool_call_count",
        "tool_errors",
    )
    return {
        field: round(float(variant[field]) - float(baseline[field]), 6)
        for field in fields
    }


def compare_reports(
    baseline: dict[str, Any],
    variant: dict[str, Any],
) -> dict[str, Any]:
    baseline_identity = _identity(baseline)
    variant_identity = _identity(variant)
    if baseline_identity["corpus_version"] != variant_identity["corpus_version"]:
        raise ValueError("reports use different corpus versions")
    if baseline_identity["fixture_version"] != variant_identity["fixture_version"]:
        raise ValueError("reports use different fixture versions")

    baseline_cases = {
        case["case_id"]: case
        for case in baseline.get("cases", [])
        if isinstance(case, dict) and isinstance(case.get("case_id"), str)
    }
    variant_cases = {
        case["case_id"]: case
        for case in variant.get("cases", [])
        if isinstance(case, dict) and isinstance(case.get("case_id"), str)
    }
    baseline_ids = set(baseline_cases)
    variant_ids = set(variant_cases)
    shared = sorted(baseline_ids & variant_ids)

    cases: list[dict[str, Any]] = []
    for case_id in shared:
        baseline_metrics = _case_metrics(baseline_cases[case_id])
        variant_metrics = _case_metrics(variant_cases[case_id])
        cases.append(
            {
                "case_id": case_id,
                "baseline": baseline_metrics,
                "variant": variant_metrics,
                "delta_variant_minus_baseline": _delta(
                    baseline_metrics,
                    variant_metrics,
                ),
                "status_changed": (
                    baseline_metrics["status"] != variant_metrics["status"]
                ),
                "checks_changed": (
                    baseline_metrics["checks_passed"]
                    != variant_metrics["checks_passed"]
                ),
                "backend_fingerprint_changed": (
                    baseline_metrics["system_fingerprints"]
                    != variant_metrics["system_fingerprints"]
                ),
            }
        )

    return {
        "baseline": baseline_identity,
        "variant": variant_identity,
        "baseline_summary": baseline.get("summary"),
        "variant_summary": variant.get("summary"),
        "baseline_abort": baseline.get("abort"),
        "variant_abort": variant.get("abort"),
        "comparability": {
            "both_unaborted": (
                baseline.get("abort") is None
                and variant.get("abort") is None
            ),
            "same_provider": (
                baseline_identity["llm_provider"] == variant_identity["llm_provider"]
            ),
            "same_model": (
                baseline_identity["llm_model"] == variant_identity["llm_model"]
            ),
            "same_provider_config": (
                baseline_identity["llm_config_hash"]
                == variant_identity["llm_config_hash"]
            ),
            "same_case_set": baseline_ids == variant_ids,
        },
        "shared_case_count": len(shared),
        "missing_from_baseline": sorted(variant_ids - baseline_ids),
        "missing_from_variant": sorted(baseline_ids - variant_ids),
        "cases": cases,
        "note": (
            "This report is descriptive only. It deliberately does not "
            "rank prompts or select a winner."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("baseline")
    parser.add_argument("variant")
    parser.add_argument("--output")
    args = parser.parse_args()

    baseline = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
    variant = json.loads(Path(args.variant).read_text(encoding="utf-8"))
    comparison = compare_reports(baseline, variant)
    rendered = json.dumps(comparison, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        Path(args.output).write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")


if __name__ == "__main__":
    main()
