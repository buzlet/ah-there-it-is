"""Validate the committed evaluation corpus and fixture compatibility."""

from __future__ import annotations

import argparse
from collections import Counter

from ah_there_it_is.eval_corpus import load_corpus
from ah_there_it_is.eval_fixture import FIXTURE_VERSION


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("corpus", nargs="?", default="eval/corpus-v1.json")
    args = parser.parse_args()

    corpus = load_corpus(args.corpus)
    ids = [case.id for case in corpus.cases]
    duplicates = sorted(case_id for case_id, count in Counter(ids).items() if count > 1)
    if duplicates:
        raise SystemExit("duplicate case ids: " + ", ".join(duplicates))
    if corpus.fixture != FIXTURE_VERSION:
        raise SystemExit(
            f"corpus fixture {corpus.fixture!r} != code fixture {FIXTURE_VERSION!r}"
        )
    groups = Counter(case.group for case in corpus.cases)
    print(f"{corpus.version}: {len(corpus.cases)} cases; fixture={corpus.fixture}")
    print("groups:", ", ".join(f"{name}={count}" for name, count in sorted(groups.items())))


if __name__ == "__main__":
    main()
