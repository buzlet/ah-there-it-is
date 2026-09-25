"""Fail-closed one-level compensation for the preceding agent mutation turn."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ah_there_it_is.agent.receipts import MutationReceipt
from ah_there_it_is.db.models import AgentRunLog, Event, Item, ItemMedia, utc_now
from ah_there_it_is.services.inventory import InventoryService


class UndoUnavailableError(ValueError):
    """The immediately preceding turn cannot be compensated safely."""


class UndoService:
    SUPPORTED = {
        "create_item", "update_item", "change_item_quantity", "move_item",
        "take_item", "mark_item_location_unknown", "remove_item", "restore_item",
        "attach_item_photo", "update_item_photo", "detach_item_photo",
    }

    def __init__(self, session: Session, *, autocommit: bool = False) -> None:
        self.session = session
        self.autocommit = autocommit
        self.inventory = InventoryService(session, autocommit=False)

    def eligible_run(self, conversation_id: int) -> AgentRunLog | None:
        return self.session.scalar(
            select(AgentRunLog)
            .where(
                AgentRunLog.conversation_id == conversation_id,
                AgentRunLog.status == "completed",
            )
            .order_by(AgentRunLog.id.desc())
            .limit(1)
        )

    def undo(self, conversation_id: int) -> tuple[AgentRunLog, tuple[int, ...]]:
        run = self.eligible_run(conversation_id)
        if run is None:
            raise UndoUnavailableError("Undo unavailable: there is no preceding completed turn")
        if not run.mutation_receipts:
            raise UndoUnavailableError(
                "Undo unavailable: the immediately preceding turn made no committed changes"
            )
        receipts = tuple(
            MutationReceipt.model_validate(value) for value in run.mutation_receipts
        )
        if any(receipt.operation == "undo_last_action" for receipt in receipts):
            raise UndoUnavailableError("Undo unavailable: redo is not supported")
        changed = tuple(receipt for receipt in receipts if receipt.changed)
        if not changed or any(receipt.operation not in self.SUPPORTED for receipt in changed):
            raise UndoUnavailableError(
                "Undo unavailable: the complete preceding turn is not safely compensatable"
            )

        compensated: list[int] = []
        try:
            for receipt in reversed(changed):
                self._compensate(receipt, undo_of_run_id=run.id)
                compensated.extend(receipt.affected_item_ids)
            self.session.flush()
            if self.autocommit:
                self.session.commit()
        except Exception:
            if self.autocommit:
                self.session.rollback()
            raise
        return run, tuple(sorted(set(compensated)))

    def _compensate(self, receipt: MutationReceipt, *, undo_of_run_id: int) -> None:
        if receipt.entity_type == "media":
            self._compensate_media(receipt, undo_of_run_id=undo_of_run_id)
            return
        source_id = int(receipt.compensation.get("source_item_id", receipt.entity_id))
        for item_id in receipt.affected_item_ids:
            expected = receipt.after.get(str(item_id))
            item = self.session.get(Item, item_id)
            if expected is None or item is None or self._snapshot(item) != expected:
                raise UndoUnavailableError(
                    f"Undo unavailable: Item id={item_id} no longer matches the recorded post-state"
                )

        if receipt.operation == "create_item":
            item = self.inventory.get_item(receipt.entity_id)
            target = {**self._snapshot(item), "state": "removed", "location_id": None,
                      "location_status": "not_applicable",
                      "removal_reason": "undo: item creation"}
            self._restore_snapshot(item, target, receipt, undo_of_run_id)
            return

        if receipt.split is not None:
            child_id = int(receipt.split["child_item_id"])
            child = self.inventory.get_item(child_id)
            source_before = receipt.before.get(str(source_id))
            if source_before is None:
                raise UndoUnavailableError("Undo unavailable: split receipt lacks source evidence")
            target = {
                **self._snapshot(child),
                "state": source_before["state"],
                "location_id": source_before["location_id"],
                "location_status": source_before["location_status"],
                "removal_reason": source_before["removal_reason"],
            }
            self._restore_snapshot(child, target, receipt, undo_of_run_id)
            return

        before = receipt.before.get(str(source_id))
        if before is None:
            raise UndoUnavailableError("Undo unavailable: receipt lacks before-state evidence")
        self._restore_snapshot(
            self.inventory.get_item(source_id), before, receipt, undo_of_run_id
        )

    def _compensate_media(
        self, receipt: MutationReceipt, *, undo_of_run_id: int
    ) -> None:
        media_id = receipt.entity_id
        operation = receipt.operation
        item_id = receipt.compensation.get("item_id")
        if item_id is None or not receipt.affected_item_ids:
            raise UndoUnavailableError("Undo unavailable: photo receipt lacks its parent Item")
        item_id = int(item_id)
        if receipt.affected_item_ids != (item_id,):
            raise UndoUnavailableError("Undo unavailable: photo receipt parent evidence changed")

        current = self.session.get(ItemMedia, media_id)
        expected = receipt.after.get(str(media_id))
        if operation in {"attach_item_photo", "update_item_photo"}:
            if current is None or self._media_snapshot(current) != expected:
                raise UndoUnavailableError(
                    f"Undo unavailable: photo id={media_id} no longer matches the recorded post-state"
                )
        elif operation == "detach_item_photo":
            if current is not None:
                raise UndoUnavailableError(
                    f"Undo unavailable: detached photo id={media_id} was recreated or changed"
                )
        else:
            raise UndoUnavailableError(f"Undo unavailable: unsupported photo operation {operation}")

        before = receipt.before.get(str(media_id))
        parent = self.inventory.get_item(item_id)
        if operation == "attach_item_photo":
            self.inventory.detach_item_photo(media_id)
        elif operation == "update_item_photo":
            if before is None:
                raise UndoUnavailableError("Undo unavailable: photo update lacks prior metadata")
            self.inventory.update_item_photo(
                media_id, caption=before["caption"], position=before["position"]
            )
        elif operation == "detach_item_photo":
            if before is None:
                raise UndoUnavailableError("Undo unavailable: photo detach lacks prior metadata")
            self.inventory.restore_item_photo(
                media_id,
                item_id,
                before["provider"],
                before["media_reference"],
                caption=before["caption"],
                position=before["position"],
            )
        self.session.add(
            Event(
                event_type="item_undo_compensated",
                item=parent,
                payload={
                    "undo_of_run_id": undo_of_run_id,
                    "operation": operation,
                    "media_id": media_id,
                    "before": before,
                    "after": receipt.after.get(str(media_id)),
                },
            )
        )

    def _restore_snapshot(
        self,
        item: Item,
        target: dict[str, Any],
        receipt: MutationReceipt,
        undo_of_run_id: int,
    ) -> None:
        current = self._snapshot(item)
        item.name = target["name"]
        item.normalized_name = self.inventory._normalized_nonblank(target["name"])
        item.description = target["description"]
        item.state = target["state"]
        item.category_id = target["category_id"]
        item.current_location_id = target["location_id"]
        item.location_status = target["location_status"]
        item.quantity_mode = target["quantity_mode"]
        item.quantity = target["quantity"]
        item.removal_reason = target["removal_reason"]
        item.attributes = dict(target["attributes"])
        if [alias.name for alias in item.aliases] != target["aliases"]:
            item.aliases.clear()
            self.session.flush()
            self.inventory._replace_aliases(item, target["aliases"])
        if [link.tag.name for link in item.tag_links] != target["tags"]:
            item.tag_links.clear()
            self.session.flush()
            self.inventory._replace_tags(item, target["tags"])
        item.updated_at = utc_now()
        self.session.add(Event(
            event_type="item_undo_compensated",
            item=item,
            from_location_id=current["location_id"],
            to_location_id=target["location_id"],
            payload={
                "undo_of_run_id": undo_of_run_id,
                "operation": receipt.operation,
                "before": current,
                "after": target,
                "split_child": receipt.split is not None,
            },
        ))

    @staticmethod
    def _snapshot(item: Item) -> dict[str, Any]:
        return {
            "id": item.id,
            "name": item.name,
            "description": item.description,
            "state": item.state,
            "quantity_mode": item.quantity_mode,
            "quantity": item.quantity,
            "removal_reason": item.removal_reason,
            "category_id": item.category_id,
            "location_id": item.current_location_id,
            "location_status": item.location_status,
            "attributes": dict(item.attributes),
            "aliases": [alias.name for alias in item.aliases],
            "tags": [link.tag.name for link in item.tag_links],
        }

    @staticmethod
    def _media_snapshot(media: ItemMedia) -> dict[str, Any]:
        return {
            "id": media.id,
            "media_id": media.id,
            "item_id": media.item_id,
            "provider": media.provider,
            "media_reference": media.media_reference,
            "caption": media.caption,
            "position": media.position,
        }
