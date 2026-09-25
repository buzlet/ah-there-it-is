"""SQLAlchemy persistence models for the inventory domain."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from ah_there_it_is.domain.states import ItemState, LocationStatus, QuantityMode


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Category(Base):
    __tablename__ = "categories"
    __table_args__ = (
        UniqueConstraint("parent_id", "normalized_name", name="uq_category_parent_name"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("categories.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(200))
    normalized_name: Mapped[str] = mapped_column(String(200), index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    parent: Mapped["Category | None"] = relationship(
        remote_side="Category.id", back_populates="children"
    )
    children: Mapped[list["Category"]] = relationship(back_populates="parent")
    items: Mapped[list["Item"]] = relationship(back_populates="category")


class Location(Base):
    __tablename__ = "locations"
    __table_args__ = (
        UniqueConstraint("parent_id", "normalized_name", name="uq_location_parent_name"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("locations.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(200))
    normalized_name: Mapped[str] = mapped_column(String(200), index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    parent: Mapped["Location | None"] = relationship(
        remote_side="Location.id", back_populates="children"
    )
    children: Mapped[list["Location"]] = relationship(back_populates="parent")
    items: Mapped[list["Item"]] = relationship(back_populates="current_location")


class Item(Base):
    __tablename__ = "items"
    __table_args__ = (
        CheckConstraint(
            "(quantity_mode IN ('exact', 'approximate') "
            "AND quantity IS NOT NULL AND quantity >= 1) OR "
            "(quantity_mode = 'unknown' AND quantity IS NULL)",
            name="ck_items_quantity_truth",
        ),
        Index("ix_items_normalized_name_category", "normalized_name", "category_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(300))
    normalized_name: Mapped[str] = mapped_column(String(300), index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    state: Mapped[str] = mapped_column(String(32), default=ItemState.UNKNOWN.value)
    category_id: Mapped[int | None] = mapped_column(
        ForeignKey("categories.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    current_location_id: Mapped[int | None] = mapped_column(
        ForeignKey("locations.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    location_status: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=LocationStatus.UNKNOWN.value
    )
    quantity_mode: Mapped[str] = mapped_column(
        String(32),
        default=QuantityMode.EXACT.value,
        server_default=QuantityMode.EXACT.value,
        nullable=False,
    )
    quantity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    removal_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    attributes: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    category: Mapped[Category | None] = relationship(back_populates="items")
    current_location: Mapped[Location | None] = relationship(back_populates="items")
    aliases: Mapped[list["Alias"]] = relationship(
        back_populates="item", cascade="all, delete-orphan"
    )
    tag_links: Mapped[list["ItemTag"]] = relationship(
        back_populates="item", cascade="all, delete-orphan"
    )
    events: Mapped[list["Event"]] = relationship(back_populates="item")
    media: Mapped[list["ItemMedia"]] = relationship(
        back_populates="item",
        cascade="all, delete-orphan",
        order_by="ItemMedia.position, ItemMedia.id",
    )


class ItemMedia(Base):
    """An opaque external photo reference attached to one Item."""

    __tablename__ = "item_media"
    __table_args__ = (
        UniqueConstraint(
            "item_id",
            "provider",
            "media_reference",
            name="uq_item_media_item_provider_reference",
        ),
        CheckConstraint("length(trim(provider)) > 0", name="ck_item_media_provider_nonblank"),
        CheckConstraint(
            "length(trim(media_reference)) > 0",
            name="ck_item_media_reference_nonblank",
        ),
        CheckConstraint("position >= 0", name="ck_item_media_position_nonnegative"),
        Index("ix_item_media_item_position", "item_id", "position", "id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(
        ForeignKey("items.id", ondelete="CASCADE"), nullable=False, index=True
    )
    provider: Mapped[str] = mapped_column(String(100), nullable=False)
    media_reference: Mapped[str] = mapped_column(String(1000), nullable=False)
    caption: Mapped[str | None] = mapped_column(Text, nullable=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    item: Mapped[Item] = relationship(back_populates="media")


class Alias(Base):
    __tablename__ = "aliases"
    __table_args__ = (
        UniqueConstraint("item_id", "normalized_name", name="uq_alias_item_name"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(
        ForeignKey("items.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(300))
    normalized_name: Mapped[str] = mapped_column(String(300), index=True)

    item: Mapped[Item] = relationship(back_populates="aliases")


class Tag(Base):
    __tablename__ = "tags"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    normalized_name: Mapped[str] = mapped_column(String(100), unique=True, index=True)

    item_links: Mapped[list["ItemTag"]] = relationship(
        back_populates="tag", cascade="all, delete-orphan"
    )


class ItemTag(Base):
    __tablename__ = "item_tags"

    item_id: Mapped[int] = mapped_column(
        ForeignKey("items.id", ondelete="CASCADE"), primary_key=True
    )
    tag_id: Mapped[int] = mapped_column(
        ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True, index=True
    )

    item: Mapped[Item] = relationship(back_populates="tag_links")
    tag: Mapped[Tag] = relationship(back_populates="item_links")


class Event(Base):
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(primary_key=True)
    event_type: Mapped[str] = mapped_column(String(50), index=True)
    item_id: Mapped[int | None] = mapped_column(
        ForeignKey("items.id", ondelete="SET NULL"), nullable=True, index=True
    )
    from_location_id: Mapped[int | None] = mapped_column(
        ForeignKey("locations.id", ondelete="RESTRICT"), nullable=True
    )
    to_location_id: Mapped[int | None] = mapped_column(
        ForeignKey("locations.id", ondelete="RESTRICT"), nullable=True
    )
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    original_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False, index=True
    )

    item: Mapped[Item | None] = relationship(back_populates="events")
    from_location: Mapped[Location | None] = relationship(
        foreign_keys=[from_location_id]
    )
    to_location: Mapped[Location | None] = relationship(foreign_keys=[to_location_id])


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    runs: Mapped[list["AgentRunLog"]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan"
    )
    messages: Mapped[list["Message"]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="Message.id",
    )


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False, index=True
    )

    conversation: Mapped[Conversation] = relationship(back_populates="messages")


class AgentRunLog(Base):
    """Replay-oriented log of one user->agent execution."""

    __tablename__ = "agent_run_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_message_id: Mapped[int | None] = mapped_column(
        ForeignKey("messages.id", ondelete="SET NULL"), nullable=True, index=True
    )
    assistant_message_id: Mapped[int | None] = mapped_column(
        ForeignKey("messages.id", ondelete="SET NULL"), nullable=True, unique=True, index=True
    )
    prompt_version: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    prompt_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    system_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    llm_provider: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    llm_model: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    llm_config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    input_messages: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    tool_trace: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    mutation_receipts: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, default=list, server_default="[]", nullable=False
    )
    final_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    rounds: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False, index=True
    )

    conversation: Mapped[Conversation] = relationship(back_populates="runs")
    experiment_runs: Mapped[list["ExperimentRun"]] = relationship(
        back_populates="source_run", cascade="all, delete-orphan"
    )
    feedback: Mapped["AgentFeedback | None"] = relationship(
        back_populates="run", cascade="all, delete-orphan", uselist=False
    )


class ChatRequestRecord(Base):
    """Local idempotency gate for one logical chat submission."""

    __tablename__ = "chat_requests"
    __table_args__ = (
        CheckConstraint(
            "status IN ('processing', 'completed', 'failed')",
            name="ck_chat_requests_status",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    request_key: Mapped[str] = mapped_column(
        String(128), nullable=False, unique=True, index=True
    )
    requested_conversation_id: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )
    message: Mapped[str] = mapped_column(Text, nullable=False)
    source_identity: Mapped[str | None] = mapped_column(String(200), nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="processing", index=True
    )
    agent_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("agent_run_logs.id", ondelete="SET NULL"),
        nullable=True,
        unique=True,
        index=True,
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    recovered_from_id: Mapped[int | None] = mapped_column(
        ForeignKey("chat_requests.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    recovery_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    run: Mapped[AgentRunLog | None] = relationship(
        foreign_keys=[agent_run_id]
    )


class AgentFeedback(Base):
    __tablename__ = "agent_feedback"
    __table_args__ = (
        CheckConstraint("rating >= 1 AND rating <= 5", name="ck_agent_feedback_rating"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    agent_run_id: Mapped[int] = mapped_column(
        ForeignKey("agent_run_logs.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    rating: Mapped[int] = mapped_column(Integer, nullable=False)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    run: Mapped[AgentRunLog] = relationship(back_populates="feedback")


class ExperimentRun(Base):
    """One prompt/model replay against captured evidence from a source run."""

    __tablename__ = "experiment_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_run_id: Mapped[int] = mapped_column(
        ForeignKey("agent_run_logs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    experiment_name: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    prompt_version: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    prompt_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    system_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    llm_provider: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    llm_model: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    llm_config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    input_messages: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    tool_trace: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    final_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    rounds: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    divergence_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False, index=True
    )

    source_run: Mapped[AgentRunLog] = relationship(back_populates="experiment_runs")
    review: Mapped["ExperimentReview | None"] = relationship(
        back_populates="experiment_run", cascade="all, delete-orphan", uselist=False
    )


class ExperimentReview(Base):
    __tablename__ = "experiment_reviews"
    __table_args__ = (
        CheckConstraint(
            "choice IN ('baseline', 'variant', 'tie', 'both_bad')",
            name="ck_experiment_review_choice",
        ),
        CheckConstraint(
            "variant_rating IS NULL OR (variant_rating >= 1 AND variant_rating <= 5)",
            name="ck_experiment_review_variant_rating",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    experiment_run_id: Mapped[int] = mapped_column(
        ForeignKey("experiment_runs.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    choice: Mapped[str] = mapped_column(String(20), nullable=False)
    variant_rating: Mapped[int | None] = mapped_column(Integer, nullable=True)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    experiment_run: Mapped[ExperimentRun] = relationship(back_populates="review")
