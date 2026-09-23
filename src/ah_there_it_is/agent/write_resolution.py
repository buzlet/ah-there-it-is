# write_resolution.py
"""Strong, database-wide identity evidence for agent writes."""

from __future__ import annotations

from sqlalchemy import select, union
from sqlalchemy.orm import Session

from ah_there_it_is.db.models import Alias, Category, Item, Location
from ah_there_it_is.domain.names import normalize_name


class WriteResolver:
    def __init__(self, session: Session) -> None:
        self.session = session

    def resolve(self, entity_type: str, query: str) -> int | None:
        identity = normalize_name(query)
        if not identity:
            return None
        if entity_type == "item":
            # UNION removes duplicate evidence for the same Item, while retaining
            # every other Item even when the read search returned only one row.
            matches = union(
                select(Item.id).where(Item.normalized_name == identity),
                select(Alias.item_id).where(Alias.normalized_name == identity),
            )
            ids = list(self.session.scalars(matches))
        elif entity_type in {"location", "category"}:
            model = Location if entity_type == "location" else Category
            rows = list(
                self.session.execute(
                    select(model.id, model.parent_id, model.normalized_name)
                )
            )
            nodes = {row.id: (row.parent_id, row.normalized_name) for row in rows}
            leaves = {node_id for node_id, (_, name) in nodes.items() if name == identity}
            # A bare leaf is never disambiguated by a root node's path.
            # For a path-shaped query, include any identical leaf names too:
            # otherwise the same text could point at two different nodes.
            if "/" in identity:
                parts = [normalize_name(part) for part in query.split("/")]
                path = " / ".join(parts) if all(parts) else ""
                paths = {
                    node_id for node_id in nodes
                    if path and self._path(node_id, nodes) == path
                }
                ids = list(leaves | paths)
            else:
                ids = list(leaves)
        else:
            return None
        return ids[0] if len(ids) == 1 else None

    @staticmethod
    def _path(node_id: int, nodes: dict[int, tuple[int | None, str]]) -> str:
        parts: list[str] = []
        seen: set[int] = set()
        while node_id in nodes:
            if node_id in seen:
                return ""
            seen.add(node_id)
            parent_id, name = nodes[node_id]
            parts.append(name)
            if parent_id is None:
                break
            node_id = parent_id
        else:
            return ""
        return " / ".join(reversed(parts))
