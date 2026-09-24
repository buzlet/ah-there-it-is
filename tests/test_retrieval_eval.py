# test_retrieval_eval.py
from __future__ import annotations

import json
from pathlib import Path

import ah_there_it_is.retrieval_eval as retrieval_eval


CORPUS = Path(__file__).resolve().parents[1] / "eval" / "retrieval-robustness-v1.json"


def test_retrieval_corpus_is_versioned_explicit_and_multilingual() -> None:
    corpus = retrieval_eval.load_retrieval_corpus(CORPUS)

    assert corpus.version == "retrieval-robustness-v1"
    assert corpus.fixture_version == "synthetic-inventory-v1"
    assert len(corpus.cases) == 86
    assert len({case.id for case in corpus.cases}) == len(corpus.cases)
    assert {
        language: sum(case.language == language for case in corpus.cases)
        for language in ("en", "ru", "uk")
    } == {"en": 28, "ru": 27, "uk": 31}
    assert {case.expected.kind for case in corpus.cases} == {
        "top_n",
        "ambiguity",
        "no_result",
    }
    assert all(
        case.expected.kind == "no_result" or case.expected.match_types
        for case in corpus.cases
    )
    assert any("/" in case.query for case in corpus.cases)
    assert any("Об’єктив" in case.query for case in corpus.cases)
    assert any(
        observation.query_class == "transliteration"
        for observation in corpus.observations
    )


def test_offline_report_gates_cases_but_reports_diagnostic_and_observations() -> None:
    corpus = retrieval_eval.load_retrieval_corpus(CORPUS)

    report = retrieval_eval.run_retrieval_evaluation(corpus)

    assert report["summary"] == {"total": 86, "passed": 86, "failed": 0}
    assert report["per_language"] == {
        "en": {"total": 28, "passed": 28, "failed": 0},
        "ru": {"total": 27, "passed": 27, "failed": 0},
        "uk": {"total": 31, "passed": 31, "failed": 0},
    }
    diagnostic = report["candidate_starvation_diagnostic"]
    assert diagnostic["gating"] is False
    assert diagnostic["fixture_item_count"] == 36
    assert diagnostic["fts_candidate_limit"] == 20
    assert isinstance(diagnostic["target_fts_rank"], int)
    assert isinstance(diagnostic["target_returned"], bool)
    assert report["summary"]["failed"] == sum(
        not case["passed"] for case in report["cases"]
    )
    assert all(not observation["gating"] for observation in report["observations"])
    assert all(
        isinstance(observation["target_returned"], bool)
        for observation in report["observations"]
    )


def test_cli_writes_machine_readable_report_and_returns_gate_status(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    output = tmp_path / "nested" / "retrieval-report.json"
    fake_report = {
        "report_version": "retrieval-evaluation-report-v1",
        "summary": {"total": 1, "passed": 1, "failed": 0},
    }
    monkeypatch.setattr(retrieval_eval, "load_retrieval_corpus", lambda _path: object())
    monkeypatch.setattr(
        retrieval_eval,
        "run_retrieval_evaluation",
        lambda _corpus: fake_report,
    )

    exit_code = retrieval_eval.main(
        ["--corpus", str(CORPUS), "--output", str(output)]
    )

    assert exit_code == 0
    assert json.loads(output.read_text(encoding="utf-8")) == fake_report
    assert '"failed": 0' in capsys.readouterr().out
