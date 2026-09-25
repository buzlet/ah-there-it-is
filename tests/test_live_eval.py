from __future__ import annotations

import json
from pathlib import Path
import sys

from sqlalchemy import func, select

from ah_there_it_is.db.models import Event
from ah_there_it_is.eval_corpus import load_corpus
from ah_there_it_is.eval_fixture import FIXTURE_VERSION, seed_inventory_fixture
from ah_there_it_is.live_eval import run_case
from ah_there_it_is.services.search import SearchService


CORPUS = Path(__file__).resolve().parents[1] / "eval" / "corpus-v1.json"


def test_corpus_v1_is_versioned_unique_and_large_enough() -> None:
    corpus = load_corpus(CORPUS)
    assert corpus.version == "inventory-corpus-v1"
    assert corpus.fixture == FIXTURE_VERSION
    assert len(corpus.cases) == 71
    assert len({case.id for case in corpus.cases}) == len(corpus.cases)
    assert {case.group for case in corpus.cases} >= {
        "find",
        "move",
        "create",
        "ambiguity",
        "update",
        "history",
        "location",
        "language",
        "safety",
    }


def test_fixture_contains_deliberate_ambiguity_and_searchable_aliases(session) -> None:
    ids = seed_inventory_fixture(session)
    search = SearchService(session)

    assert ids.items["unit"] != ids.items["dt830b"]
    assert search.search_items("красный мультиметр")[0].id == ids.items["dt830b"]
    assert search.search_items("переходник для SATA диска")[0].id == ids.items["usb_sata"]

    cabinets = [
        candidate
        for candidate in search.search_locations("Шкаф", limit=10)
        if candidate.match_type == "exact_name"
    ]
    assert len(cabinets) == 2
    assert {candidate.id for candidate in cabinets} == {
        ids.locations["study_cabinet"],
        ids.locations["balcony_cabinet"],
    }


def test_offline_live_eval_plumbing_can_move_without_touching_external_state(monkeypatch) -> None:
    from ah_there_it_is.eval_corpus import EvaluationCase, ExpectedCheck

    case = EvaluationCase(
        id="offline-move",
        group="plumbing",
        turns=["Переложил CH341A в Средний ящик."],
        focus="Offline plumbing only.",
        checks=[
            ExpectedCheck(
                kind="item_location",
                item_query="CH341A",
                location_query="Средний ящик",
            )
        ],
    )
    monkeypatch.setenv("AH_THERE_IT_IS_LLM_PROVIDER", "heuristic")
    from ah_there_it_is.config import get_settings

    get_settings.cache_clear()
    try:
        result = run_case(
            case,
            prompt="inventory test prompt",
            prompt_version="test",
            allow_heuristic=True,
        )
    finally:
        get_settings.cache_clear()

    assert result["status"] == "completed"
    assert result["checks_passed"] is True
    assert len(result["turns"]) == 1
    assert result["turns"][0]["tool_trace"]
    assert result["turns"][0]["llm_model"] == "heuristic-v1"
    assert result["wall_seconds"] >= 0


def test_fixture_seed_creates_history_events(session) -> None:
    seed_inventory_fixture(session)
    count = session.scalar(select(func.count(Event.id)))
    assert count == 13


def test_case_without_automated_checks_is_not_reported_as_passed(monkeypatch) -> None:
    from ah_there_it_is.eval_corpus import EvaluationCase
    from ah_there_it_is.config import get_settings

    monkeypatch.setenv("AH_THERE_IT_IS_LLM_PROVIDER", "heuristic")
    get_settings.cache_clear()
    try:
        result = run_case(
            EvaluationCase(
                id="manual-only",
                group="manual",
                turns=["Где GTX 1070?"],
                focus="Manual-only case.",
            ),
            prompt="test",
            prompt_version="test",
            allow_heuristic=True,
        )
    finally:
        get_settings.cache_clear()

    assert result["status"] == "completed"
    assert result["checks"] == []
    assert result["checks_passed"] is None


def test_failed_live_case_never_counts_automatic_checks_as_passed(monkeypatch) -> None:
    from ah_there_it_is.agent.runner import AgentRunner
    from ah_there_it_is.config import get_settings
    from ah_there_it_is.eval_corpus import EvaluationCase, ExpectedCheck

    monkeypatch.setenv("AH_THERE_IT_IS_LLM_PROVIDER", "heuristic")
    monkeypatch.setattr(
        AgentRunner,
        "run",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("provider failed")),
    )
    get_settings.cache_clear()
    try:
        result = run_case(
            EvaluationCase(
                id="failed-provider",
                group="plumbing",
                turns=["where GTX 1070"],
                focus="Failure accounting.",
                checks=[ExpectedCheck(kind="no_mutation")],
            ),
            prompt="test",
            prompt_version="test",
            allow_heuristic=True,
        )
    finally:
        get_settings.cache_clear()

    assert result["status"] == "failed"
    assert result["checks"][0]["ok"] is True
    assert result["checks_passed"] is False


def test_live_eval_main_writes_progress_and_report(monkeypatch, tmp_path, capsys) -> None:
    import ah_there_it_is.live_eval as live_eval
    from ah_there_it_is.config import get_settings

    output = tmp_path / "report.json"
    monkeypatch.setenv("AH_THERE_IT_IS_LLM_PROVIDER", "heuristic")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "live_eval",
            "--corpus",
            str(CORPUS),
            "--case",
            "find-01",
            "--output",
            str(output),
            "--allow-heuristic",
        ],
    )
    get_settings.cache_clear()
    try:
        live_eval.main()
    finally:
        get_settings.cache_clear()

    report = json.loads(output.read_text(encoding="utf-8"))
    captured = capsys.readouterr().out
    assert report["summary"]["count"] == 1
    assert report["cases"][0]["case_id"] == "find-01"
    assert "[live-eval] case 1/1 start find-01" in captured
    assert "[live-eval] case 1/1 done find-01" in captured
