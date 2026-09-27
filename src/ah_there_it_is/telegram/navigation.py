"""Read-only Telegram location browsing and compact inventory rendering."""

from __future__ import annotations

from dataclasses import dataclass
import html
import math
import re

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ah_there_it_is.db.models import Item, Location


LOCATION_PAGE_SIZE = 8
ITEM_PAGE_SIZE = 5
MAX_BREADCRUMB_DEPTH = 512
MAX_BREADCRUMB_LENGTH = 300
MAX_ITEM_LABEL_LENGTH = 70
MAX_BUTTON_LABEL_LENGTH = 48
_CONTROL_CHARACTERS = re.compile(r"[\x00-\x1f\x7f]")


@dataclass(frozen=True)
class TelegramLocationRef:
    id: int
    name: str


@dataclass(frozen=True)
class TelegramItemView:
    name: str
    quantity: int | None
    quantity_mode: str


@dataclass(frozen=True)
class TelegramLocationListView:
    page: int
    page_count: int
    total: int
    locations: tuple[TelegramLocationRef, ...]


@dataclass(frozen=True)
class TelegramLocationContentsView:
    location_id: int
    name: str
    breadcrumb: str
    parent_id: int | None
    root_page: int
    item_page: int
    item_page_count: int
    item_total: int
    items: tuple[TelegramItemView, ...]
    child_page: int
    child_page_count: int
    child_total: int
    children: tuple[TelegramLocationRef, ...]


@dataclass(frozen=True)
class TelegramNavigationAction:
    kind: str
    location_id: int | None = None
    page: int = 1
    root_page: int = 1


class TelegramLocationBrowser:
    """Bounded direct-child/direct-item reads for the Telegram adapter."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def root_page(self, page: int = 1) -> TelegramLocationListView:
        total = int(
            self.session.scalar(
                select(func.count(Location.id)).where(Location.parent_id.is_(None))
            )
            or 0
        )
        page, page_count = _bounded_page(page, total, LOCATION_PAGE_SIZE)
        rows = self.session.execute(
            select(Location.id, Location.name)
            .where(Location.parent_id.is_(None))
            .order_by(Location.normalized_name, Location.id)
            .offset((page - 1) * LOCATION_PAGE_SIZE)
            .limit(LOCATION_PAGE_SIZE)
        )
        return TelegramLocationListView(
            page=page,
            page_count=page_count,
            total=total,
            locations=tuple(TelegramLocationRef(id=row.id, name=row.name) for row in rows),
        )

    def location_contents(
        self,
        location_id: int,
        *,
        root_page: int = 1,
        item_page: int = 1,
        child_page: int = 1,
    ) -> TelegramLocationContentsView | None:
        if type(location_id) is not int or location_id <= 0:
            return None
        row = self._location_row(location_id)
        if row is None:
            return None
        ancestors = self._breadcrumb_names(row.id, row.name, row.parent_id)

        item_query = select(Item.name, Item.quantity, Item.quantity_mode).where(
            Item.current_location_id == location_id,
            Item.location_status == "known",
        )
        item_total = int(
            self.session.scalar(
                select(func.count(Item.id)).where(
                    Item.current_location_id == location_id,
                    Item.location_status == "known",
                )
            )
            or 0
        )
        item_page, item_page_count = _bounded_page(item_page, item_total, ITEM_PAGE_SIZE)
        item_rows = self.session.execute(
            item_query.order_by(Item.normalized_name, Item.id)
            .offset((item_page - 1) * ITEM_PAGE_SIZE)
            .limit(ITEM_PAGE_SIZE)
        )

        child_total = int(
            self.session.scalar(
                select(func.count(Location.id)).where(Location.parent_id == location_id)
            )
            or 0
        )
        child_page, child_page_count = _bounded_page(
            child_page, child_total, LOCATION_PAGE_SIZE
        )
        child_rows = self.session.execute(
            select(Location.id, Location.name)
            .where(Location.parent_id == location_id)
            .order_by(Location.normalized_name, Location.id)
            .offset((child_page - 1) * LOCATION_PAGE_SIZE)
            .limit(LOCATION_PAGE_SIZE)
        )
        return TelegramLocationContentsView(
            location_id=row.id,
            name=row.name,
            breadcrumb=_compact_breadcrumb(ancestors),
            parent_id=row.parent_id,
            root_page=max(1, root_page),
            item_page=item_page,
            item_page_count=item_page_count,
            item_total=item_total,
            items=tuple(
                TelegramItemView(
                    name=item.name,
                    quantity=item.quantity,
                    quantity_mode=item.quantity_mode,
                )
                for item in item_rows
            ),
            child_page=child_page,
            child_page_count=child_page_count,
            child_total=child_total,
            children=tuple(
                TelegramLocationRef(id=child.id, name=child.name)
                for child in child_rows
            ),
        )

    def _location_row(self, location_id: int):
        return self.session.execute(
            select(Location.id, Location.name, Location.parent_id)
            .where(Location.id == location_id)
            .execution_options(populate_existing=True)
        ).one_or_none()

    def _breadcrumb_names(
        self, location_id: int, name: str, parent_id: int | None
    ) -> list[str]:
        names = [name]
        seen = {location_id}
        current_id = parent_id
        while current_id is not None:
            if len(seen) >= MAX_BREADCRUMB_DEPTH or current_id in seen:
                raise ValueError("location hierarchy is not safe to display")
            seen.add(current_id)
            row = self._location_row(current_id)
            if row is None:
                raise ValueError("location hierarchy is incomplete")
            names.append(row.name)
            current_id = row.parent_id
        names.reverse()
        return names


class TelegramLocationRenderer:
    """Render structured inventory data as escaped Telegram HTML and buttons."""

    def render_root(self, view: TelegramLocationListView) -> str:
        lines = ["<b>Места хранения</b>"]
        if view.total == 0:
            lines.extend(("", "Пока нет мест хранения."))
        elif view.page_count > 1:
            lines.extend(("", f"Страница {view.page}/{view.page_count}"))
        return "\n".join(lines)

    def root_keyboard(self, view: TelegramLocationListView) -> dict[str, object] | None:
        rows = [
            [self._button(_short_label(location.name), f"t1:l:{location.id}:{view.page}")]
            for location in view.locations
        ]
        if view.page_count > 1:
            navigation = []
            if view.page > 1:
                navigation.append(self._button("‹", f"t1:r:{view.page - 1}"))
            if view.page < view.page_count:
                navigation.append(self._button("›", f"t1:r:{view.page + 1}"))
            rows.append(navigation)
        return {"inline_keyboard": rows} if rows else None

    def render_location(self, view: TelegramLocationContentsView) -> str:
        lines = [f"<b>{_escape(_display_text(view.breadcrumb, 300))}</b>"]
        if view.item_page_count > 1:
            lines.extend(("", f"Вещи {view.item_page}/{view.item_page_count}"))
        for item in view.items:
            name = _escape(_display_text(item.name, MAX_ITEM_LABEL_LENGTH))
            quantity = _quantity_suffix(item.quantity, item.quantity_mode)
            lines.append(f"• {name}{quantity}")
        if view.item_total == 0:
            lines.extend(("", "Вещей пока нет."))
        lines.extend(("", "Места:"))
        if view.child_total == 0:
            lines.append("Вложенных мест пока нет.")
        elif view.child_page_count > 1:
            lines.append(f"Страница мест {view.child_page}/{view.child_page_count}")
        return "\n".join(lines)

    def location_keyboard(
        self, view: TelegramLocationContentsView
    ) -> dict[str, object]:
        rows = [
            [
                self._button(
                    _short_label(child.name),
                    f"t1:l:{child.id}:{view.root_page}",
                )
            ]
            for child in view.children
        ]
        if view.child_page_count > 1:
            navigation = []
            if view.child_page > 1:
                navigation.append(
                    self._button("‹ Места", f"t1:c:{view.location_id}:{view.child_page - 1}:{view.root_page}")
                )
            if view.child_page < view.child_page_count:
                navigation.append(
                    self._button("Места ›", f"t1:c:{view.location_id}:{view.child_page + 1}:{view.root_page}")
                )
            rows.append(navigation)
        if view.item_page_count > 1:
            navigation = []
            if view.item_page > 1:
                navigation.append(
                    self._button("‹ Вещи", f"t1:i:{view.location_id}:{view.item_page - 1}:{view.root_page}")
                )
            if view.item_page < view.item_page_count:
                navigation.append(
                    self._button("Вещи ›", f"t1:i:{view.location_id}:{view.item_page + 1}:{view.root_page}")
                )
            rows.append(navigation)
        if view.parent_id is None:
            rows.append([self._button("← Все места", f"t1:r:{view.root_page}")])
        else:
            rows.append(
                [self._button("← Назад", f"t1:b:{view.location_id}:{view.root_page}")]
            )
        return {"inline_keyboard": rows}

    @staticmethod
    def _button(label: str, callback_data: str) -> dict[str, str]:
        if not callback_data or len(callback_data.encode("utf-8")) > 64:
            raise ValueError("Telegram callback data exceeds the Bot API limit")
        return {"text": label, "callback_data": callback_data}


def _bounded_page(page: int, total: int, page_size: int) -> tuple[int, int]:
    if type(page) is not int or page < 1:
        page = 1
    page_count = max(1, math.ceil(total / page_size))
    return min(page, page_count), page_count


def parse_navigation_callback(data: str | None) -> TelegramNavigationAction | None:
    """Parse versioned navigation-only payloads without accepting free-form IDs."""
    if not isinstance(data, str) or len(data.encode("utf-8")) > 64:
        return None
    parts = data.split(":")
    if len(parts) == 3 and parts[:2] == ["t1", "r"]:
        page = _positive_decimal(parts[2], max_digits=9)
        return TelegramNavigationAction("root", page=page) if page is not None else None
    if len(parts) == 4 and parts[0] == "t1" and parts[1] in {"l", "b"}:
        location_id = _positive_decimal(parts[2], max_digits=19)
        root_page = _positive_decimal(parts[3], max_digits=9)
        if (
            location_id is None
            or location_id >= 2**63
            or root_page is None
        ):
            return None
        return TelegramNavigationAction(
            "location" if parts[1] == "l" else "back",
            location_id=location_id,
            root_page=root_page,
        )
    if len(parts) in {4, 5} and parts[0] == "t1" and parts[1] in {"c", "i"}:
        location_id = _positive_decimal(parts[2], max_digits=19)
        page = _positive_decimal(parts[3], max_digits=9)
        root_page = _positive_decimal(parts[4], max_digits=9) if len(parts) == 5 else 1
        if location_id is None or location_id >= 2**63 or page is None or root_page is None:
            return None
        return TelegramNavigationAction(
            "children" if parts[1] == "c" else "items",
            location_id=location_id,
            page=page,
            root_page=root_page,
        )
    return None


def _positive_decimal(value: str, *, max_digits: int) -> int | None:
    if not value.isascii() or not value.isdecimal() or len(value) > max_digits:
        return None
    if len(value) > 1 and value.startswith("0"):
        return None
    result = int(value)
    return result if result > 0 else None


def _quantity_suffix(quantity: int | None, mode: str) -> str:
    if type(quantity) is not int or quantity < 1 or mode not in {"exact", "approximate"}:
        return ""
    prefix = "~" if mode == "approximate" else ""
    return f" — {prefix}{quantity}"


def _display_text(value: str, limit: int) -> str:
    compact = " ".join(_CONTROL_CHARACTERS.sub(" ", value).split())
    if len(compact) > limit:
        compact = compact[: max(1, limit - 1)].rstrip() + "…"
    return compact


def _compact_breadcrumb(names: list[str]) -> str:
    labels = [_display_text(name, 70) for name in names]
    full = " › ".join(labels)
    if len(full) <= MAX_BREADCRUMB_LENGTH:
        return full
    if len(labels) <= 2:
        return " › ".join(labels)
    tail: list[str] = []
    for label in reversed(labels[1:-1]):
        candidate_tail = [label, *tail]
        candidate = " › ".join([labels[0], "…", *candidate_tail, labels[-1]])
        if len(candidate) > MAX_BREADCRUMB_LENGTH:
            break
        tail = candidate_tail
    compact = " › ".join([labels[0], "…", *tail, labels[-1]])
    return compact[:MAX_BREADCRUMB_LENGTH]


def _short_label(value: str) -> str:
    return _display_text(value, MAX_BUTTON_LABEL_LENGTH)


def _escape(value: str) -> str:
    return html.escape(value, quote=False)


__all__ = [
    "ITEM_PAGE_SIZE",
    "LOCATION_PAGE_SIZE",
    "TelegramItemView",
    "TelegramLocationBrowser",
    "TelegramLocationContentsView",
    "TelegramLocationListView",
    "TelegramNavigationAction",
    "TelegramLocationRenderer",
    "TelegramLocationRef",
    "parse_navigation_callback",
]
