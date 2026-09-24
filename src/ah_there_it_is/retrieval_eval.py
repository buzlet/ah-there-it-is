# retrieval_eval.py
"""Offline, deterministic evaluation of the current item-retrieval behavior."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Literal, Sequence

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy.orm import Session

from ah_there_it_is.db.models import Base
from ah_there_it_is.db.search_schema import install_fts_schema
from ah_there_it_is.db.session import create_db_engine
from ah_there_it_is.services.inventory import InventoryService
from ah_there_it_is.services.search import SearchService


Language = Literal["en", "ru", "uk"]
MatchType = Literal[
    "exact_name",
    "exact_alias",
    "exact_attribute",
    "normalized_name",
    "normalized_alias",
    "exact_tag",
    "contains",
    "fts",
]


class RetrievalItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str
    language: Language
    name: str
    description: str | None = None
    aliases: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    attributes: dict[str, Any] = Field(default_factory=dict)
    allow_duplicate: bool = False


class RetrievalExpectation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["top_n", "ambiguity", "no_result"]
    target: str | None = None
    labels: list[str] = Field(default_factory=list)
    top_n: int = Field(default=1, ge=1)
    match_types: list[MatchType] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_kind_fields(self) -> RetrievalExpectation:
        if self.kind == "top_n":
            if not self.target or self.labels or not self.match_types:
                raise ValueError("top_n requires target and match_types only")
        elif self.kind == "ambiguity":
            if self.target or len(self.labels) < 2 or not self.match_types:
                raise ValueError(
                    "ambiguity requires at least two labels and match_types"
                )
        elif self.target or self.labels or self.match_types:
            raise ValueError(
                "no_result must not declare a target, labels, or match_types"
            )
        return self


class RetrievalCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    language: Language
    query: str = Field(min_length=1)
    expected: RetrievalExpectation


class DiagnosticFixture(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    query: str
    result_limit: int = Field(default=5, ge=1)
    target: RetrievalItem
    target_description_chunk: str
    target_description_repetitions: int = Field(default=300, ge=1)
    target_description_suffix: str
    distractor_count: int = Field(ge=21)
    distractor_label_prefix: str
    distractor_name_template: str
    distractor_description: str


class RetrievalObservation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    language: Language
    query: str
    query_class: Literal[
        "typo",
        "transliteration",
        "inflection",
        "ukrainian_apostrophe_variant",
    ]
    target: str
    note: str


class RetrievalCorpus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str
    fixture_version: str
    result_limit: int = Field(default=5, ge=1)
    items: list[RetrievalItem] = Field(min_length=1)
    cases: list[RetrievalCase] = Field(min_length=60)
    diagnostic: DiagnosticFixture
    observations: list[RetrievalObservation] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_references_and_coverage(self) -> RetrievalCorpus:
        labels = [item.label for item in self.items]
        if len(set(labels)) != len(labels):
            raise ValueError("fixture item labels must be unique")
        known_labels = set(labels)
        case_ids = [case.id for case in self.cases]
        if len(set(case_ids)) != len(case_ids):
            raise ValueError("case IDs must be unique")
        if any(case.expected.top_n > self.result_limit for case in self.cases):
            raise ValueError("case top_n must not exceed result_limit")
        referenced = {
            case.expected.target
            for case in self.cases
            if case.expected.target is not None
        }
        referenced.update(
            label for case in self.cases for label in case.expected.labels
        )
        referenced.update(observation.target for observation in self.observations)
        if not referenced <= known_labels:
            raise ValueError(
                f"unknown semantic labels: {sorted(referenced - known_labels)}"
            )
        if self.diagnostic.target.label in known_labels:
            raise ValueError(
                "diagnostic target label must be separate from gating fixture"
            )
        language_counts = {
            language: sum(case.language == language for case in self.cases)
            for language in ("en", "ru", "uk")
        }
        if any(count < 15 for count in language_counts.values()):
            raise ValueError(f"insufficient language coverage: {language_counts}")
        return self


def load_retrieval_corpus(path: str | Path) -> RetrievalCorpus:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return RetrievalCorpus.model_validate(data)


def _new_session() -> tuple[Any, Session]:
    engine = create_db_engine("sqlite://")
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        install_fts_schema(connection)
    return engine, Session(engine)


def _seed_items(
    session: Session,
    items: Sequence[RetrievalItem],
) -> tuple[dict[str, int], dict[int, str]]:
    inventory = InventoryService(session)
    label_to_id: dict[str, int] = {}
    id_to_label: dict[int, str] = {}
    for spec in items:
        item = inventory.create_item(
            spec.name,
            description=spec.description,
            aliases=spec.aliases,
            tags=spec.tags,
            attributes=spec.attributes,
            original_text="offline retrieval evaluation fixture",
            allow_duplicate=spec.allow_duplicate,
        )
        label_to_id[spec.label] = item.id
        id_to_label[item.id] = spec.label
    return label_to_id, id_to_label


def _project_results(
    results: Sequence[Any], id_to_label: dict[int, str]
) -> list[dict[str, Any]]:
    return [
        {
            "id": result.id,
            "label": id_to_label.get(result.id, f"unmapped:{result.id}"),
            "name": result.name,
            "match_type": result.match_type,
            "score": result.score,
        }
        for result in results
    ]


def _evaluate_case(
    case: RetrievalCase,
    search: SearchService,
    id_to_label: dict[int, str],
    result_limit: int,
) -> dict[str, Any]:
    results = _project_results(
        search.search_items(case.query, limit=result_limit),
        id_to_label,
    )
    expected = case.expected
    failures: list[str] = []

    if expected.kind == "no_result":
        if results:
            failures.append(
                "expected no result; received "
                + ", ".join(result["label"] for result in results)
            )
    elif expected.kind == "top_n":
        top_results = results[: expected.top_n]
        target = next(
            (result for result in top_results if result["label"] == expected.target),
            None,
        )
        if target is None:
            failures.append(
                f"expected {expected.target} within top {expected.top_n}"
            )
        elif target["match_type"] not in expected.match_types:
            failures.append(
                f"{expected.target} used match type {target['match_type']}; "
                f"accepted: {expected.match_types}"
            )
    else:
        actual = {result["label"] for result in results}
        wanted = set(expected.labels)
        if actual != wanted:
            failures.append(
                "ambiguity set mismatch; "
                f"expected {sorted(wanted)}, got {sorted(actual)}"
            )
        wrong_types = [
            f"{result['label']}:{result['match_type']}"
            for result in results
            if result["match_type"] not in expected.match_types
        ]
        if wrong_types:
            failures.append(
                f"unexpected ambiguity match types: {', '.join(wrong_types)}"
            )

    return {
        "id": case.id,
        "language": case.language,
        "query": case.query,
        "expected": expected.model_dump(mode="json"),
        "results": results,
        "passed": not failures,
        "failure_reasons": failures,
    }


def _evaluate_observations(
    corpus: RetrievalCorpus,
    search: SearchService,
    id_to_label: dict[int, str],
) -> list[dict[str, Any]]:
    observations: list[dict[str, Any]] = []
    for observation in corpus.observations:
        results = _project_results(
            search.search_items(observation.query, limit=corpus.result_limit),
            id_to_label,
        )
        observations.append(
            {
                "id": observation.id,
                "language": observation.language,
                "query": observation.query,
                "query_class": observation.query_class,
                "target": observation.target,
                "target_returned": any(
                    result["label"] == observation.target for result in results
                ),
                "results": results,
                "note": observation.note,
                "gating": False,
            }
        )
    return observations


def _evaluate_diagnostic(spec: DiagnosticFixture) -> dict[str, Any]:
    engine, session = _new_session()
    try:
        target_description = " ".join(
            [spec.target_description_chunk] * spec.target_description_repetitions
        )
        target_description = f"{target_description} {spec.target_description_suffix}"
        target = spec.target.model_copy(
            update={"description": target_description}
        )
        items = [target]
        for index in range(1, spec.distractor_count + 1):
            items.append(
                RetrievalItem(
                    label=f"{spec.distractor_label_prefix}_{index:02d}",
                    language=target.language,
                    name=spec.distractor_name_template.format(index=index),
                    description=spec.distractor_description,
                )
            )
        label_to_id, id_to_label = _seed_items(session, items)
        target_id = label_to_id[target.label]
        search = SearchService(session)
        candidate_limit = max(spec.result_limit * 4, 20)
        expanded_fts = search._fts_item_ids(spec.query, limit=len(items) + 1)
        target_fts_rank = next(
            (
                index
                for index, (item_id, _rank) in enumerate(expanded_fts, start=1)
                if item_id == target_id
            ),
            None,
        )
        results = _project_results(
            search.search_items(spec.query, limit=spec.result_limit),
            id_to_label,
        )
        target_returned = any(
            result["label"] == target.label for result in results
        )
        return {
            "id": spec.id,
            "query": spec.query,
            "gating": False,
            "fixture_item_count": len(items),
            "distractor_count": spec.distractor_count,
            "result_limit": spec.result_limit,
            "fts_candidate_limit": candidate_limit,
            "target_label": target.label,
            "target_id": target_id,
            "target_fts_rank": target_fts_rank,
            "target_inside_bounded_fts_pool": (
                target_fts_rank is not None and target_fts_rank <= candidate_limit
            ),
            "target_returned": target_returned,
            "results": results,
        }
    finally:
        session.close()
        engine.dispose()


def run_retrieval_evaluation(corpus: RetrievalCorpus) -> dict[str, Any]:
    engine, session = _new_session()
    try:
        _, id_to_label = _seed_items(session, corpus.items)
        search = SearchService(session)
        case_results = [
            _evaluate_case(case, search, id_to_label, corpus.result_limit)
            for case in corpus.cases
        ]
        language_summary = {
            language: {
                "total": sum(result["language"] == language for result in case_results),
                "passed": sum(
                    result["language"] == language and result["passed"]
                    for result in case_results
                ),
                "failed": sum(
                    result["language"] == language and not result["passed"]
                    for result in case_results
                ),
            }
            for language in ("en", "ru", "uk")
        }
        summary = {
            "total": len(case_results),
            "passed": sum(result["passed"] for result in case_results),
            "failed": sum(not result["passed"] for result in case_results),
        }
        observations = _evaluate_observations(
            corpus,
            search,
            id_to_label,
        )
    finally:
        session.close()
        engine.dispose()

    return {
        "report_version": "retrieval-evaluation-report-v1",
        "corpus_version": corpus.version,
        "fixture_version": corpus.fixture_version,
        "summary": summary,
        "per_language": language_summary,
        "cases": case_results,
        "candidate_starvation_diagnostic": _evaluate_diagnostic(corpus.diagnostic),
        "observations": observations,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", required=True)
    parser.add_argument("--output", default="/tmp/ah-there-it-is-retrieval-eval.json")
    args = parser.parse_args(argv)

    corpus = load_retrieval_corpus(args.corpus)
    report = run_retrieval_evaluation(corpus)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report["summary"], sort_keys=True))
    print(f"report: {output}")
    return 0 if report["summary"]["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
