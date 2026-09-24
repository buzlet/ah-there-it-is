"""Deterministic candidate retrieval used before any LLM reasoning."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session, selectinload

from ah_there_it_is.db.models import Alias, Category, Item, ItemTag, Location, Tag
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
    EXACT_PATH = 975
    NORMALIZED_NAME = 900
    NORMALIZED_ALIAS = 875
    EXACT_TAG = 825
    CONTAINS = 700
    FTS = 600
    FTS_MIN_SCAN_ROWS = 100
    FTS_MAX_SCAN_ROWS = 500

    def __init__(self, session: Session) -> None:
        self.session = session

    def search_items(self, query: str, *, limit: int = 5) -> list[ItemSearchCandidate]:
        query = query.strip()
        if not query or limit < 1:
            return []

        identity = normalize_name(query)
        search_key = normalize_search_text(query)
        candidate_limit = max(limit * 4, 20)
        fts_scan_limit = self._fts_scan_limit(candidate_limit)

        fts_rows = self._fts_item_ids(query, limit=fts_scan_limit)
        fts_by_id = dict(fts_rows)
        candidate_ids = {item_id for item_id, _ in fts_rows}
        candidate_ids.update(
            self.session.scalars(
                select(Item.id)
                .where(Item.normalized_name == identity)
                .order_by(Item.id)
                .limit(candidate_limit)
            )
        )
        candidate_ids.update(
            self.session.scalars(
                select(Alias.item_id)
                .where(Alias.normalized_name == identity)
                .order_by(Alias.item_id)
                .limit(candidate_limit)
            )
        )
        candidate_ids.update(
            self.session.scalars(
                select(ItemTag.item_id)
                .join(Tag, Tag.id == ItemTag.tag_id)
                .where(Tag.normalized_name == identity)
                .order_by(ItemTag.item_id)
                .limit(candidate_limit)
            )
        )
        candidate_ids.update(
            self._exact_attribute_item_ids(identity, limit=candidate_limit)
        )

        if identity:
            contains_pattern = f"%{identity}%"
            candidate_ids.update(
                self.session.scalars(
                    select(Item.id)
                    .where(Item.normalized_name.like(contains_pattern))
                    .order_by(Item.id)
                    .limit(candidate_limit)
                )
            )
            candidate_ids.update(
                self.session.scalars(
                    select(Alias.item_id)
                    .where(Alias.normalized_name.like(contains_pattern))
                    .order_by(Alias.item_id)
                    .limit(candidate_limit)
                )
            )

        if not candidate_ids:
            return []

        item_stmt = (
            select(Item)
            .options(
                selectinload(Item.aliases),
                selectinload(Item.tag_links).selectinload(ItemTag.tag),
            )
            .where(Item.id.in_(candidate_ids))
            .order_by(Item.id)
        )
        items_by_id = {
            item.id: item
            for item in self.session.scalars(item_stmt)
        }

        ranked: dict[int, _Ranked] = {}
        for item_id, item in items_by_id.items():
            candidate = self._rank_item_python(item, identity, search_key)
            if candidate is not None:
                ranked[item_id] = candidate

            fts_rank = fts_by_id.get(item_id)
            if fts_rank is None or not self._fts_overlap_ok(item, search_key):
                continue
            proposed = _Ranked(self.FTS, "fts", fts_rank)
            current = ranked.get(item_id)
            if current is None or proposed.score > current.score:
                ranked[item_id] = proposed
            elif current.score == proposed.score and current.fts_rank is None:
                ranked[item_id] = _Ranked(
                    current.score,
                    current.match_type,
                    fts_rank,
                )

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
            item = items_by_id.get(item_id)
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
                    current_location_id=item.current_location_id,
                    location_status=item.location_status,
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

    def _fts_overlap_ok(self, item: Item, search_key: str) -> bool:
        query_tokens = set(search_key.split())
        if len(query_tokens) < 2:
            return True
        searchable_parts = [
            normalize_search_text(item.name),
            normalize_search_text(item.description or ""),
            *(normalize_search_text(alias.name) for alias in item.aliases),
            *(normalize_search_text(link.tag.name) for link in item.tag_links),
            *self._attribute_values(item.attributes),
        ]
        candidate_tokens = set(" ".join(searchable_parts).split())
        return len(query_tokens.intersection(candidate_tokens)) >= 2

    def _exact_attribute_item_ids(
        self,
        identity: str,
        *,
        limit: int,
    ) -> list[int]:
        if not identity:
            return []
        rows = self.session.execute(
            text(
                """
                SELECT DISTINCT items.id AS item_id
                FROM items, json_tree(items.attributes) AS attribute
                WHERE attribute.type NOT IN ('object', 'array', 'null')
                  AND lower(trim(CAST(attribute.value AS TEXT))) = :identity
                ORDER BY items.id
                LIMIT :limit
                """
            ),
            {"identity": identity, "limit": limit},
        )
        return [int(row.item_id) for row in rows]

    @classmethod
    def _fts_scan_limit(cls, candidate_limit: int) -> int:
        """Overscan FTS without exceeding the per-request row bound."""
        return min(max(candidate_limit, cls.FTS_MIN_SCAN_ROWS), cls.FTS_MAX_SCAN_ROWS)

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
        nodes = list(self.session.scalars(select(model).order_by(model.id)))
        candidates: list[SearchCandidate] = []

        # Preserve the original strong tree-search semantics first.
        for node in nodes:
            path = self._path(node) or node.name
            leaf_search = normalize_search_text(node.name)
            path_search = normalize_search_text(path)
            if node.normalized_name == identity:
                score, match = self.EXACT_NAME, "exact_name"
            elif (
                search_key
                and (
                    path_search == search_key
                    or path_search.endswith(" " + search_key)
                )
            ):
                score, match = self.EXACT_PATH, "exact_path"
            elif leaf_search == search_key:
                score, match = self.NORMALIZED_NAME, "normalized_name"
            elif search_key and search_key in leaf_search:
                score, match = self.CONTAINS + 50, "contains"
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

        if candidates:
            return sorted(candidates, key=lambda c: (-c.score, c.path or "", c.id))[:limit]

        # Fallback only when the original search found nothing. Natural phrases
        # may contain an exact leaf plus inflected ancestry, e.g.
        # "средний ящик стола". Prefer the longer, more specific leaf.
        for node in nodes:
            path = self._path(node) or node.name
            leaf_search = normalize_search_text(node.name)
            if not leaf_search or leaf_search not in search_key:
                continue
            specificity = min(len(leaf_search.split()), 3)
            candidates.append(
                SearchCandidate(
                    id=node.id,
                    entity_type=entity_type,  # type: ignore[arg-type]
                    name=node.name,
                    path=path,
                    description=node.description,
                    match_type="contains",
                    score=self.CONTAINS + 50 * specificity,
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
