"""Merge compatible partial/resumed live-evaluation reports."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


def _canonical(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _identity(report: dict[str, Any]) -> tuple[Any, ...]:
    provider = report.get("provider")
    provider = provider if isinstance(provider, dict) else {}
    return (
        report.get("corpus_version"),
        report.get("fixture_version"),
        report.get("prompt_version"),
        report.get("prompt_hash"),
        provider.get("provider"),
        provider.get("model"),
        hashlib.sha256(
            _canonical(provider.get("config") or {}).encode("utf-8")
        ).hexdigest(),
    )


def _execution_key(case: dict[str, Any]) -> tuple[str, int]:
    case_id = case.get("case_id")
    if not isinstance(case_id, str):
        raise ValueError("case is missing string case_id")
    trial = case.get("trial", 1)
    if not isinstance(trial, int) or trial < 1:
        raise ValueError(f"invalid trial for {case_id!r}")
    return case_id, trial


def _summarize(cases: list[dict[str, Any]]) -> dict[str, int]:
    checked = [case for case in cases if case.get("checks_passed") is not None]
    return {
        "count": len(cases),
        "completed": sum(case.get("status") == "completed" for case in cases),
        "failed": sum(case.get("status") == "failed" for case in cases),
        "automatically_checked": len(checked),
        "automatic_checks_passed": sum(
            case.get("checks_passed") is True for case in checked
        ),
        "manual_review_required": len(cases) - len(checked),
    }


def merge_reports(reports: list[dict[str, Any]]) -> dict[str, Any]:
    if not reports:
        raise ValueError("at least one report is required")
    identity = _identity(reports[0])
    for report in reports[1:]:
        if _identity(report) != identity:
            raise ValueError(
                "reports have different corpus/fixture/prompt/provider/model/config identity"
            )

    merged_cases: dict[tuple[str, int], dict[str, Any]] = {}
    for report in reports:
        cases = report.get("cases")
        if not isinstance(cases, list):
            raise ValueError("report cases must be a list")
        for case in cases:
            if not isinstance(case, dict):
                raise ValueError("case must be an object")
            key = _execution_key(case)
            existing = merged_cases.get(key)
            if existing is not None and _canonical(existing) != _canonical(case):
                raise ValueError(
                    f"conflicting execution {key[0]}#r{key[1]} across reports"
                )
            merged_cases[key] = case

    ordered = [
        merged_cases[key]
        for key in sorted(merged_cases, key=lambda item: (item[1], item[0]))
    ]
    base = dict(reports[0])
    base["cases"] = ordered
    base["summary"] = _summarize(ordered)
    trials = sorted({key[1] for key in merged_cases})
    base["trial_start"] = trials[0] if trials else 1
    base["repetitions"] = len(trials)
    base["merged_from_reports"] = len(reports)
    return base


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reports", nargs="+")
    parser.add_argument("--output")
    args = parser.parse_args()

    reports = [
        json.loads(Path(path).read_text(encoding="utf-8"))
        for path in args.reports
    ]
    merged = merge_reports(reports)
    rendered = json.dumps(merged, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        Path(args.output).write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")


if __name__ == "__main__":
    main()
