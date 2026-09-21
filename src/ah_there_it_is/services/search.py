"""Deterministic candidate retrieval used before any LLM reasoning."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session, selectinload

from ah_there_it_is.db.models import Category, Item, ItemTag, Location, Tag
from ah_there_it_is.domain.names import normalize_name, normalize_search_text
from ah_there_it_is.domain.search import ItemSearchCandidate, SearchCandidate


@dataclass(frozen=True)
class _Ranked:
    score: int
    match_type: str
    fts_rank: float | None = None


class SearchService:
    """Return small, stable-ID candidate lists with deterministic ranking."""

    EXACT_NAME = 1000
    EXACT_ALIAS = 950
    EXACT_ATTRIBUTE = 925
    NORMALIZED_NAME = 900
    NORMALIZED_ALIAS = 875
    EXACT_TAG = 825
    CONTAINS = 700
    FTS = 600

    def __init__(self, session: Session) -> None:
        self.session = session

    def search_items(self, query: str, *, limit: int = 5) -> list[ItemSearchCandidate]:
        query = query.strip()
        if not query or limit < 1:
            return []

        identity = normalize_name(query)
        search_key = normalize_search_text(query)
        ranked: dict[int, _Ranked] = {}

        item_stmt = (
            select(Item)
            .options(
                selectinload(Item.aliases),
                selectinload(Item.tag_links).selectinload(ItemTag.tag),
            )
            .order_by(Item.id)
        )
        for item in self.session.scalars(item_stmt):
            candidate = self._rank_item_python(item, identity, search_key)
            if candidate is not None:
                ranked[item.id] = candidate

        for item_id, fts_rank in self._fts_item_ids(query, limit=max(limit * 4, 20)):
            current = ranked.get(item_id)
            proposed = _Ranked(self.FTS, "fts", fts_rank)
            if current is None or proposed.score > current.score:
                ranked[item_id] = proposed
            elif current.score == proposed.score and current.fts_rank is None:
                ranked[item_id] = _Ranked(current.score, current.match_type, fts_rank)

        ordered = sorted(
            ranked.items(),
            key=lambda pair: (
                -pair[1].score,
                pair[1].fts_rank if pair[1].fts_rank is not None else 0.0,
                pair[0],
            ),
        )[:limit]

        results: list[ItemSearchCandidate] = []
        for item_id, rank in ordered:
            item = self.session.get(Item, item_id)
            if item is None:
                continue
            results.append(
                ItemSearchCandidate(
                    id=item.id,
                    name=item.name,
                    match_type=rank.match_type,  # type: ignore[arg-type]
                    score=rank.score,
                    description=item.description,
                    state=item.state,
                    location_id=item.current_location_id,
                    location_path=self._path(item.current_location),
                    category_id=item.category_id,
                    category_path=self._path(item.category),
                    fts_rank=rank.fts_rank,
                )
            )
        return results

    def search_locations(self, query: str, *, limit: int = 5) -> list[SearchCandidate]:
        return self._search_tree(Location, query, "location", limit)

    def search_categories(self, query: str, *, limit: int = 5) -> list[SearchCandidate]:
        return self._search_tree(Category, query, "category", limit)

    def search_tags(self, query: str, *, limit: int = 5) -> list[SearchCandidate]:
        query = query.strip()
        if not query or limit < 1:
            return []
        identity = normalize_name(query)
        search_key = normalize_search_text(query)
        candidates: list[SearchCandidate] = []
        for tag in self.session.scalars(select(Tag).order_by(Tag.id)):
            tag_search = normalize_search_text(tag.name)
            if tag.normalized_name == identity:
                score, match = self.EXACT_NAME, "exact_name"
            elif tag_search == search_key:
                score, match = self.NORMALIZED_NAME, "normalized_name"
            elif search_key and search_key in tag_search:
                score, match = self.CONTAINS, "contains"
            else:
                continue
            candidates.append(
                SearchCandidate(
                    id=tag.id,
                    entity_type="tag",
                    name=tag.name,
                    match_type=match,  # type: ignore[arg-type]
                    score=score,
                )
            )
        return sorted(candidates, key=lambda c: (-c.score, c.id))[:limit]

    def _rank_item_python(
        self, item: Item, identity: str, search_key: str
    ) -> _Ranked | None:
        if item.normalized_name == identity:
            return _Ranked(self.EXACT_NAME, "exact_name")

        alias_identity = {alias.normalized_name for alias in item.aliases}
        if identity in alias_identity:
            return _Ranked(self.EXACT_ALIAS, "exact_alias")

        if search_key and search_key in self._attribute_values(item.attributes):
            return _Ranked(self.EXACT_ATTRIBUTE, "exact_attribute")

        if normalize_search_text(item.name) == search_key:
            return _Ranked(self.NORMALIZED_NAME, "normalized_name")

        if any(normalize_search_text(alias.name) == search_key for alias in item.aliases):
            return _Ranked(self.NORMALIZED_ALIAS, "normalized_alias")

        if any(link.tag.normalized_name == identity for link in item.tag_links):
            return _Ranked(self.EXACT_TAG, "exact_tag")

        searchable = " ".join(
            filter(
                None,
                [
                    normalize_search_text(item.name),
                    *(normalize_search_text(alias.name) for alias in item.aliases),
                ],
            )
        )
        if search_key and search_key in searchable:
            return _Ranked(self.CONTAINS, "contains")
        return None

    def _fts_item_ids(self, query: str, *, limit: int) -> list[tuple[int, float]]:
        expression = self._fts_expression(query)
        if not expression:
            return []
        rows = self.session.execute(
            text(
                """
                SELECT rowid AS item_id, bm25(item_search_fts) AS rank
                FROM item_search_fts
                WHERE item_search_fts MATCH :query
                ORDER BY rank, rowid
                LIMIT :limit
                """
            ),
            {"query": expression, "limit": limit},
        )
        return [(int(row.item_id), float(row.rank)) for row in rows]

    @staticmethod
    def _fts_expression(query: str) -> str:
        tokens = normalize_search_text(query).split()
        if not tokens:
            return ""
        escaped = [token.replace('"', '""') for token in tokens]
        return " OR ".join(f'"{token}"*' for token in escaped)

    def _search_tree(
        self,
        model: type[Location] | type[Category],
        query: str,
        entity_type: str,
        limit: int,
    ) -> list[SearchCandidate]:
        query = query.strip()
        if not query or limit < 1:
            return []
        identity = normalize_name(query)
        search_key = normalize_search_text(query)
        candidates: list[SearchCandidate] = []

        for node in self.session.scalars(select(model).order_by(model.id)):
            path = self._path(node) or node.name
            leaf_search = normalize_search_text(node.name)
            path_search = normalize_search_text(path)
            if node.normalized_name == identity:
                score, match = self.EXACT_NAME, "exact_name"
            elif leaf_search == search_key:
                score, match = self.NORMALIZED_NAME, "normalized_name"
            elif search_key and search_key in leaf_search:
                score, match = self.CONTAINS + 50, "contains"
            elif leaf_search and leaf_search in search_key:
                # Natural phrases often contain the exact leaf plus inflected
                # ancestry, e.g. "средний ящик стола". Prefer the longer,
                # more specific leaf over a generic ancestor such as "стол".
                specificity = min(len(leaf_search.split()), 3)
                score, match = self.CONTAINS + 50 * specificity, "contains"
            elif self._all_tokens_present(search_key, path_search):
                score, match = self.CONTAINS, "contains"
            else:
                continue
            candidates.append(
                SearchCandidate(
                    id=node.id,
                    entity_type=entity_type,  # type: ignore[arg-type]
                    name=node.name,
                    path=path,
                    description=node.description,
                    match_type=match,  # type: ignore[arg-type]
                    score=score,
                )
            )
        return sorted(candidates, key=lambda c: (-c.score, c.path or "", c.id))[:limit]

    @staticmethod
    def _all_tokens_present(query: str, candidate: str) -> bool:
        tokens = query.split()
        return bool(tokens) and all(token in candidate for token in tokens)

    @staticmethod
    def _attribute_values(attributes: dict[str, Any]) -> set[str]:
        values: set[str] = set()

        def visit(value: Any) -> None:
            if isinstance(value, dict):
                for nested in value.values():
                    visit(nested)
            elif isinstance(value, (list, tuple, set)):
                for nested in value:
                    visit(nested)
            elif value is not None:
                normalized = normalize_search_text(str(value))
                if normalized:
                    values.add(normalized)

        visit(attributes)
        return values

    @staticmethod
    def _path(node: Location | Category | None) -> str | None:
        if node is None:
            return None
        names: list[str] = []
        seen: set[int] = set()
        current: Location | Category | None = node
        while current is not None:
            if current.id in seen:
                raise RuntimeError("cycle detected in hierarchy")
            seen.add(current.id)
            names.append(current.name)
            current = current.parent
        return " / ".join(reversed(names))
