"""Strong, database-wide canonical identity evidence for agent writes."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ah_there_it_is.db.models import Alias, Category, Item, Location
from ah_there_it_is.domain.names import normalize_name
from ah_there_it_is.domain.russian_semantics import (
    canonicalize_location_name, canonicalize_name, parse_location_phrase,
)


class WriteResolver:
    def __init__(self, session: Session) -> None:
        self.session = session

    def resolve(self, entity_type: str, query: str) -> int | None:
        """Return an entity ID only for one strong canonical identity match."""
        return self.resolve_with_evidence(entity_type, query)["entity_id"]

    def resolve_with_evidence(self, entity_type: str, query: str) -> dict[str, object]:
        """Return an inspectable decision without promoting retrieval similarity."""
        canonical = (
            canonicalize_location_name(query)
            if entity_type == "location"
            else canonicalize_name(query)
        )
        identity = canonical.comparison_key
        if not identity:
            return {"status": "no_exact_identity", "entity_id": None, "evidence": None}

        if entity_type == "item":
            direct_ids = set(self.session.scalars(
                select(Item.id).where(Item.normalized_name == identity)
            ))
            alias_ids = set(self.session.scalars(
                select(Alias.item_id).where(Alias.normalized_name == identity)
            ))
            ids = direct_ids | alias_ids
            if len(ids) != 1:
                return {
                    "status": "ambiguous" if ids else "no_exact_identity",
                    "entity_id": None,
                    "evidence": None,
                }
            entity_id = next(iter(ids))
            kind = "canonical_name" if entity_id in direct_ids else "canonical_alias"
            return {"status": "resolved", "entity_id": entity_id, "evidence": kind}

        if entity_type not in {"location", "category"}:
            return {"status": "no_exact_identity", "entity_id": None, "evidence": None}
        model = Location if entity_type == "location" else Category
        rows = list(self.session.execute(
            select(model.id, model.parent_id, model.normalized_name)
        ))
        nodes = {row.id: (row.parent_id, row.normalized_name) for row in rows}

        relation = parse_location_phrase(query) if entity_type == "location" else None
        if relation is not None:
            path = relation.path_key
            paths = {
                node_id for node_id in nodes
                if self._path(node_id, nodes) == path
                or self._path(node_id, nodes).endswith(" / " + path)
            }
            ids = paths
            evidence = "canonical_relational_path"
        elif "/" in identity:
            parts = [canonicalize_name(part).comparison_key for part in query.split("/")]
            path = " / ".join(parts) if all(parts) else ""
            paths = {
                node_id for node_id in nodes
                if path and self._path(node_id, nodes) == path
            }
            leaves = {
                node_id for node_id, (_, name) in nodes.items() if name == identity
            }
            ids = paths | leaves
            evidence = "canonical_full_path"
        else:
            ids = {
                node_id for node_id, (_, name) in nodes.items() if name == identity
            }
            evidence = "canonical_name"
        if len(ids) != 1:
            return {
                "status": "ambiguous" if ids else "no_exact_identity",
                "entity_id": None,
                "evidence": None,
            }
        return {
            "status": "resolved",
            "entity_id": next(iter(ids)),
            "evidence": evidence,
        }

    @staticmethod
    def _path(node_id: int, nodes: dict[int, tuple[int | None, str]]) -> str:
        parts: list[str] = []
        seen: set[int] = set()
        while node_id in nodes:
            if node_id in seen:
                return ""
            seen.add(node_id)
            parent_id, name = nodes[node_id]
            parts.append(normalize_name(name))
            if parent_id is None:
                break
            node_id = parent_id
        else:
            return ""
        return " / ".join(reversed(parts))
