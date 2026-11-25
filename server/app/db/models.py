import json
import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    cast,
    func,
    text,
    type_coerce,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import TypeDecorator, UserDefinedType

_PGVECTOR_ENABLED: bool | None = None


def set_pgvector_enabled(enabled: bool) -> None:
    global _PGVECTOR_ENABLED
    _PGVECTOR_ENABLED = bool(enabled)


def is_pgvector_enabled() -> bool:
    return bool(_PGVECTOR_ENABLED)


def pgvector_detected() -> bool | None:
    return _PGVECTOR_ENABLED


class _PgVectorType(UserDefinedType):
    cache_ok = True

    def __init__(self, dim: int = 1536) -> None:
        self.dim = int(dim)

    def get_col_spec(self, **kw: Any) -> str:
        return f"VECTOR({self.dim})"


class _PgVectorTextParam(TypeDecorator):
    """Encode list[float] as pgvector text literal '[...]' for asyncpg text parameters."""

    impl = Text
    cache_ok = True

    def process_bind_param(self, value: Any, dialect: Any) -> str | None:
        if value is None:
            return None
        if isinstance(value, str):
            return value
        return "[" + ",".join(f"{float(x):.8f}" for x in value) + "]"


class SafeVector(TypeDecorator):
    """Compile to VECTOR(dim) when pgvector is available, or JSONB fallback on plain Postgres."""

    impl = JSONB
    cache_ok = False

    def __init__(self, dim: int = 1536) -> None:
        super().__init__()
        self.dim = int(dim)

    def load_dialect_impl(self, dialect: Any) -> Any:
        if dialect.name == "postgresql" and is_pgvector_enabled():
            return dialect.type_descriptor(_PgVectorType(self.dim))
        return dialect.type_descriptor(JSONB())

    def process_bind_param(self, value: Any, dialect: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, str):
            return value
        vec = [float(x) for x in value]
        if dialect.name == "postgresql" and is_pgvector_enabled():
            return "[" + ",".join(f"{x:.8f}" for x in vec) + "]"
        return vec

    def process_result_value(self, value: Any, dialect: Any) -> list[float] | None:
        if value is None:
            return None
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
                if isinstance(parsed, list):
                    return [float(x) for x in parsed]
            except (json.JSONDecodeError, TypeError, ValueError):
                return None
            return None
        if isinstance(value, (list, tuple)):
            return [float(x) for x in value]
        return None

    def bind_expression(self, bindvalue: Any) -> Any:
        if is_pgvector_enabled():
            return cast(type_coerce(bindvalue, _PgVectorTextParam()), _PgVectorType(self.dim))
        return bindvalue

    def column_expression(self, col: Any) -> Any:
        if is_pgvector_enabled():
            return cast(col, Text)
        return col


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        Index("uq_users_display_name_lower", text("lower(display_name)"), unique=True),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    display_name: Mapped[str] = mapped_column(String(80))
    avatar_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    assistant_name: Mapped[str] = mapped_column(String(80), default="Whitz", server_default="Whitz")
    assistant_avatar_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    bio: Mapped[str] = mapped_column(String(300), default="", server_default="")
    gender: Mapped[str | None] = mapped_column(String(40), nullable=True)
    birthday: Mapped[date | None] = mapped_column(Date, nullable=True)
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    location: Mapped[str | None] = mapped_column(String(80), nullable=True)
    occupation: Mapped[str | None] = mapped_column(String(80), nullable=True)
    website: Mapped[str | None] = mapped_column(String(255), nullable=True)
    preferred_language: Mapped[str] = mapped_column(String(16), default="zh-CN", server_default="zh-CN")
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Shanghai", server_default="Asia/Shanghai")
    role: Mapped[str] = mapped_column(String(16), default="user")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    persona: Mapped[str] = mapped_column(Text, default="")
    profile_context_enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    profile_context_consented_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    memory_enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    memory_consented_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    memory_require_confirm: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    ai_reactions_enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    ai_posts_enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    ai_posts_consented_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    agent_namespace: Mapped[str] = mapped_column(String(64), unique=True)
    agent_api_key: Mapped[str] = mapped_column(String(128))
    token_version: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    membership_tier: Mapped[str] = mapped_column(String(16), default="free", server_default="free")
    membership_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    credit_anchor_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    refresh_tokens: Mapped[list["RefreshToken"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    conversations: Mapped[list["Conversation"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class DesktopLlmKey(Base):
    """Long-lived key used by the desktop app against the built-in LLM proxy."""

    __tablename__ = "desktop_llm_keys"
    __table_args__ = (Index("ix_desktop_llm_keys_user", "user_id", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    label: Mapped[str] = mapped_column(String(80), default="", server_default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    session_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    family_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    user_agent: Mapped[str | None] = mapped_column(String(256), nullable=True)
    client_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    replaced_by_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rotated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped["User"] = relationship(back_populates="refresh_tokens")


class UsageDaily(Base):
    __tablename__ = "usage_daily"
    __table_args__ = (UniqueConstraint("user_id", "day", name="uq_usage_daily_user_day"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    day: Mapped[date] = mapped_column(Date, index=True)
    messages: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    tokens: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    runs: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class CreditLedger(Base):
    """Credit bookkeeping. ``tokens`` is signed: negative for consumption."""

    __tablename__ = "credit_ledger"
    __table_args__ = (
        Index("ix_credit_ledger_user_created", "user_id", "created_at"),
        Index("ix_credit_ledger_created_at", "created_at"),
        UniqueConstraint("message_id", name="uq_credit_ledger_message"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    tokens: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    kind: Mapped[str] = mapped_column(String(16), default="consume")
    tier: Mapped[str | None] = mapped_column(String(16), nullable=True)
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    message_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    note: Mapped[str | None] = mapped_column(String(255), nullable=True)


class InviteCode(Base):
    __tablename__ = "invite_codes"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    tier: Mapped[str] = mapped_column(String(16), default="plus")
    duration_days: Mapped[int] = mapped_column(Integer, default=30, server_default="30")
    max_uses: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    used_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    note: Mapped[str | None] = mapped_column(String(200), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class InviteRedemption(Base):
    __tablename__ = "invite_redemptions"
    __table_args__ = (
        UniqueConstraint("code_id", "user_id", name="uq_invite_redemption_code_user"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("invite_codes.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    tier: Mapped[str] = mapped_column(String(16))
    duration_days: Mapped[int] = mapped_column(Integer, default=30)
    redeemed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AuditLog(Base):
    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_logs_created_at", "created_at"),
        Index("ix_audit_logs_actor_created", "actor_user_id", "created_at"),
        Index("ix_audit_logs_action_created", "action", "created_at"),
        Index("ix_audit_logs_severity_created", "severity", "created_at"),
        Index("ix_audit_logs_risk_created", "risk_score", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    actor_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    action: Mapped[str] = mapped_column(String(80), index=True)
    target_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    target_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    outcome: Mapped[str] = mapped_column(String(16), default="success")
    severity: Mapped[str] = mapped_column(String(16), default="info", index=True)
    risk_score: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(256), nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    session_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSONB, nullable=True)
    diff: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    prev_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    record_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)


class Conversation(Base):
    __tablename__ = "conversations"
    __table_args__ = (
        Index("uq_conversations_user_main", "user_id", unique=True, postgresql_where=text("kind = 'main'")),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    thread_id: Mapped[str] = mapped_column(String(128), default="", server_default="")
    kind: Mapped[str] = mapped_column(String(16), default="side", server_default="side", index=True)
    title: Mapped[str] = mapped_column(String(200), default="新旁聊")
    is_pinned: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", index=True)
    pinned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    plan: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    active_run_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    active_run_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    pending_control: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    rolling_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary_cursor_msg_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    summary_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    working_state: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    working_state_cursor_msg_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    working_state_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped[User] = relationship(back_populates="conversations")
    messages: Mapped[list["Message"]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan", order_by="Message.created_at"
    )
    files: Mapped[list["ConversationFile"]] = relationship(
        back_populates="conversation", passive_deletes=True, order_by="ConversationFile.created_at"
    )


class ConversationDigest(Base):
    """Incremental semantic & FTS summary of a side chat for main-chat cross-session memory."""

    __tablename__ = "conversation_digests"
    __table_args__ = (
        UniqueConstraint("conversation_id", name="uq_conversation_digests_conv"),
        Index("ix_conversation_digests_user_recent", "user_id", "last_message_at"),
        Index("ix_conversation_digests_search_tsv", "search_tsv", postgresql_using="gin"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(200), default="", server_default="")
    summary: Mapped[str] = mapped_column(Text, default="", server_default="")
    key_facts: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    keywords: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    message_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    last_message_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    search_tsv: Mapped[Any] = mapped_column(TSVECTOR, nullable=True)
    embedding: Mapped[list[float] | None] = mapped_column(SafeVector(1536), nullable=True)
    embedding_model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ConversationEpisode(Base):
    """Immutable topic-segmented episodic archive for long Main Chats and Side Chats (L2 Episodic Memory)."""

    __tablename__ = "conversation_episodes"
    __table_args__ = (
        Index("ix_conversation_episodes_conv_idx", "conversation_id", "episode_index"),
        Index("ix_conversation_episodes_user_ended", "user_id", "ended_at"),
        Index("ix_conversation_episodes_search_tsv", "search_tsv", postgresql_using="gin"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    conversation_kind: Mapped[str] = mapped_column(String(16), default="main", server_default="main")
    episode_index: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    topic: Mapped[str] = mapped_column(String(200), default="", server_default="")
    summary: Mapped[str] = mapped_column(Text, default="", server_default="")
    key_facts: Mapped[list[str]] = mapped_column(JSONB, default=list, server_default=text("'[]'::jsonb"))
    entities: Mapped[list[str]] = mapped_column(JSONB, default=list, server_default=text("'[]'::jsonb"))
    start_msg_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    end_msg_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    message_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    token_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    search_tsv: Mapped[Any] = mapped_column(TSVECTOR, nullable=True)
    embedding: Mapped[list[float] | None] = mapped_column(SafeVector(1536), nullable=True)
    embedding_model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ConversationFile(Base):
    __tablename__ = "conversation_files"
    __table_args__ = (
        Index("ix_conversation_files_conv_created", "conversation_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    filename: Mapped[str] = mapped_column(String(255))
    ext: Mapped[str] = mapped_column(String(24))
    mime_type: Mapped[str] = mapped_column(String(128))
    category: Mapped[str] = mapped_column(String(24))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    storage_key: Mapped[str] = mapped_column(String(512), unique=True)
    etag: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(String(24), default="pending", server_default="pending")
    index_status: Mapped[str] = mapped_column(String(24), default="ready", server_default="ready")
    indexed_chunks: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    summary: Mapped[str] = mapped_column(Text, default="", server_default="")
    keywords: Mapped[list[str]] = mapped_column(JSONB, default=list, server_default=text("'[]'::jsonb"))
    embedding_model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    index_error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    indexed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    source: Mapped[str] = mapped_column(String(24), default="user", server_default="user")
    is_global: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true", index=True)
    message_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    expires_cleanup_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    conversation: Mapped[Conversation | None] = relationship(back_populates="files")


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (
        Index("ix_messages_conv_created", "conversation_id", "created_at"),
        Index("ix_messages_conv_run", "conversation_id", "run_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(Text, default="")
    tool_name: Mapped[str | None] = mapped_column(String(80), nullable=True)
    tool_payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="completed")
    run_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    conversation: Mapped[Conversation] = relationship(back_populates="messages")
    reactions: Mapped[list["MessageReaction"]] = relationship(
        back_populates="message",
        cascade="all, delete-orphan",
        order_by="MessageReaction.created_at",
        lazy="noload",
    )


class MemoryCollection(Base):
    __tablename__ = "memory_collections"
    __table_args__ = (
        UniqueConstraint("user_id", "slug", name="uq_memory_collections_user_slug"),
        Index("ix_memory_collections_user_enabled", "user_id", "enabled"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    slug: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(80))
    description: Mapped[str] = mapped_column(String(300), default="", server_default="")
    kind: Mapped[str] = mapped_column(String(24), default="custom", server_default="custom")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    char_limit: Mapped[int] = mapped_column(Integer, default=12000, server_default="12000")
    max_entries: Mapped[int] = mapped_column(Integer, default=200, server_default="200")
    sort_order: Mapped[int] = mapped_column(Integer, default=100, server_default="100")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class MemoryEntry(Base):
    __tablename__ = "memory_entries"
    __table_args__ = (
        Index("ix_memory_entries_user_target", "user_id", "target"),
        Index("ix_memory_entries_user_collection", "user_id", "collection_id"),
        Index("ix_memory_entries_user_pinned", "user_id", "is_pinned", "priority"),
        Index("ix_memory_entries_search_tsv", "search_tsv", postgresql_using="gin"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    collection_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("memory_collections.id", ondelete="CASCADE"), nullable=True, index=True
    )
    target: Mapped[str] = mapped_column(String(64), default="memory", server_default="memory")
    title: Mapped[str] = mapped_column(String(120), default="", server_default="")
    content: Mapped[str] = mapped_column(Text)
    tags: Mapped[list[str]] = mapped_column(JSONB, default=list, server_default=text("'[]'::jsonb"))
    source: Mapped[str] = mapped_column(String(24), default="manual", server_default="manual")
    search_tsv: Mapped[Any] = mapped_column(TSVECTOR, nullable=True)
    embedding: Mapped[list[float] | None] = mapped_column(SafeVector(1536), nullable=True)
    embedding_model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    is_pinned: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", index=True)
    priority: Mapped[int] = mapped_column(Integer, default=2, server_default="2")
    last_accessed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    access_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    supersedes_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class MemoryPendingProposal(Base):
    __tablename__ = "memory_pending_proposals"
    __table_args__ = (Index("ix_memory_pending_user_status", "user_id", "status", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    collection_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("memory_collections.id", ondelete="SET NULL"), nullable=True
    )
    target: Mapped[str] = mapped_column(String(64), default="memory", server_default="memory")
    title: Mapped[str] = mapped_column(String(120), default="", server_default="")
    tags: Mapped[list[str]] = mapped_column(JSONB, default=list, server_default=text("'[]'::jsonb"))
    action: Mapped[str] = mapped_column(String(16), default="add", server_default="add")
    content: Mapped[str] = mapped_column(Text)
    old_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="pending", server_default="pending", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class UserSkill(Base):
    __tablename__ = "user_skills"
    __table_args__ = (
        UniqueConstraint("user_id", "name", name="uq_user_skills_user_name"),
        Index("ix_user_skills_user_enabled", "user_id", "enabled"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(80))
    title: Mapped[str | None] = mapped_column(String(120), nullable=True)
    description: Mapped[str] = mapped_column(String(500), default="", server_default="")
    category: Mapped[str | None] = mapped_column(String(64), nullable=True)
    content: Mapped[str] = mapped_column(Text, default="", server_default="")
    files: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    tags: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    source: Mapped[str] = mapped_column(String(24), default="custom", server_default="custom")
    repo_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    ref: Mapped[str | None] = mapped_column(String(120), nullable=True)
    path: Mapped[str | None] = mapped_column(String(300), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class SkillPendingProposal(Base):
    __tablename__ = "skill_pending_proposals"
    __table_args__ = (Index("ix_skill_pending_user_status", "user_id", "status", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    name: Mapped[str] = mapped_column(String(80))
    description: Mapped[str] = mapped_column(String(500), default="", server_default="")
    category: Mapped[str | None] = mapped_column(String(64), nullable=True)
    content: Mapped[str] = mapped_column(Text)
    files: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    action: Mapped[str] = mapped_column(String(24), default="create", server_default="create")
    source: Mapped[str] = mapped_column(String(24), default="agent", server_default="agent")
    repo_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    ref: Mapped[str | None] = mapped_column(String(120), nullable=True)
    path: Mapped[str | None] = mapped_column(String(300), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="pending", server_default="pending", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class FileChunk(Base):
    __tablename__ = "file_chunks"
    __table_args__ = (
        Index("ix_file_chunks_user_conv", "user_id", "conversation_id"),
        Index("ix_file_chunks_file_idx", "file_id", "chunk_index"),
        Index("ix_file_chunks_search_tsv", "search_tsv", postgresql_using="gin"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    file_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversation_files.id", ondelete="CASCADE"), index=True
    )
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    is_global: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true", index=True)
    chunk_index: Mapped[int] = mapped_column(Integer)
    locator: Mapped[str] = mapped_column(String(160), default="", server_default="")
    context_header: Mapped[str] = mapped_column(Text, default="", server_default="")
    section_path: Mapped[str] = mapped_column(Text, default="", server_default="")
    chunk_type: Mapped[str] = mapped_column(String(24), default="text", server_default="text")
    token_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    chunk_meta: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    content: Mapped[str] = mapped_column(Text)
    search_tsv: Mapped[Any] = mapped_column(TSVECTOR, nullable=True)
    embedding: Mapped[list[float] | None] = mapped_column(SafeVector(1536), nullable=True)
    embedding_model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class MessageChunk(Base):
    """Episodic turn-level semantic chunk for hybrid vector/trgm/FTS recall across all chats."""

    __tablename__ = "message_chunks"
    __table_args__ = (
        Index("ix_message_chunks_user_conv", "user_id", "conversation_id", "created_at"),
        Index("ix_message_chunks_search_tsv", "search_tsv", postgresql_using="gin"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    conversation_kind: Mapped[str] = mapped_column(String(16), default="side", server_default="side")
    start_msg_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    end_msg_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    context_header: Mapped[str] = mapped_column(Text, default="", server_default="")
    content: Mapped[str] = mapped_column(Text)
    token_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    search_tsv: Mapped[Any] = mapped_column(TSVECTOR, nullable=True)
    embedding: Mapped[list[float] | None] = mapped_column(SafeVector(1536), nullable=True)
    embedding_model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class RunTelemetry(Base):
    """Structured per-run telemetry for quantitative latency, cost, model, and tool analytics."""

    __tablename__ = "run_telemetry"
    __table_args__ = (
        Index("ix_run_telemetry_created", "created_at"),
        Index("ix_run_telemetry_route_created", "model_route", "created_at"),
        Index("ix_run_telemetry_status_created", "status", "created_at"),
        Index("ix_run_telemetry_user_created", "user_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True, index=True
    )
    message_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    model_route: Mapped[str] = mapped_column(String(32), default="auto", server_default="auto")
    model_name: Mapped[str] = mapped_column(String(120), default="", server_default="")
    status: Mapped[str] = mapped_column(String(24), default="completed", server_default="completed")
    ttft_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    total_tokens: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    estimated_cost_usd: Mapped[float] = mapped_column(Float, default=0.0, server_default="0")
    tool_calls_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    tool_errors_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    tools_summary: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    skills_used: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    rag_metrics: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    is_regenerated: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    hitl_denied_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class OpsAlertRule(Base):
    """Configurable threshold alert rule for operations monitoring."""

    __tablename__ = "ops_alert_rules"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(120))
    metric_key: Mapped[str] = mapped_column(String(64), index=True)
    operator: Mapped[str] = mapped_column(String(8), default="gt", server_default="gt")
    threshold: Mapped[float] = mapped_column(Float, default=0.0, server_default="0")
    window_minutes: Mapped[int] = mapped_column(Integer, default=15, server_default="15")
    cooldown_minutes: Mapped[int] = mapped_column(Integer, default=30, server_default="30")
    severity: Mapped[str] = mapped_column(String(16), default="warning", server_default="warning")
    webhook_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    last_triggered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class OpsAlertEvent(Base):
    """Triggered alert event log with acknowledgement state."""

    __tablename__ = "ops_alert_events"
    __table_args__ = (
        Index("ix_ops_alert_events_status_created", "status", "created_at"),
        Index("ix_ops_alert_events_rule_created", "rule_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    rule_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("ops_alert_rules.id", ondelete="SET NULL"), nullable=True
    )
    rule_name: Mapped[str] = mapped_column(String(120), default="", server_default="")
    metric_key: Mapped[str] = mapped_column(String(64))
    current_value: Mapped[float] = mapped_column(Float)
    threshold: Mapped[float] = mapped_column(Float)
    severity: Mapped[str] = mapped_column(String(16), default="warning", server_default="warning")
    status: Mapped[str] = mapped_column(String(16), default="firing", server_default="firing")
    message: Mapped[str] = mapped_column(String(500), default="", server_default="")
    webhook_status: Mapped[str | None] = mapped_column(String(40), nullable=True)
    acked_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    acked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class EvalRun(Base):
    """Persisted agent evaluation run for quantitative quality & regression tracking."""

    __tablename__ = "eval_runs"
    __table_args__ = (Index("ix_eval_runs_created", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    mode: Mapped[str] = mapped_column(String(24), default="dry-run", server_default="dry-run")
    dataset_name: Mapped[str] = mapped_column(String(120), default="default", server_default="default")
    total: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    passed: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    pass_rate: Mapped[float] = mapped_column(Float, default=0.0, server_default="0")
    category_scores: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    results: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    git_sha: Mapped[str | None] = mapped_column(String(64), nullable=True)
    triggered_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class MessageReaction(Base):
    """Emoji/quality reactions on messages from users (including negative) or AI (positive-only)."""

    __tablename__ = "message_reactions"
    __table_args__ = (
        UniqueConstraint("message_id", "author_type", "user_id", name="uq_message_reactions_msg_actor_user"),
        Index("ix_message_reactions_conv_created", "conversation_id", "created_at"),
        Index("ix_message_reactions_author_created", "author_type", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    message_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("messages.id", ondelete="CASCADE"), index=True
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    author_type: Mapped[str] = mapped_column(String(16), default="user", server_default="user")
    reaction: Mapped[str] = mapped_column(String(24))
    reason_code: Mapped[str | None] = mapped_column(String(40), nullable=True)
    comment: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    message: Mapped[Message] = relationship(back_populates="reactions")


class UserFeedback(Base):
    """Product-level feedback & rating submitted from user Settings."""

    __tablename__ = "user_feedbacks"
    __table_args__ = (
        Index("ix_user_feedbacks_user_created", "user_id", "created_at"),
        Index("ix_user_feedbacks_status_created", "status", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    rating: Mapped[int] = mapped_column(Integer, default=5, server_default="5")
    sentiment: Mapped[str] = mapped_column(String(16), default="positive", server_default="positive")
    category: Mapped[str] = mapped_column(String(32), default="general", server_default="general")
    content: Mapped[str] = mapped_column(Text, default="", server_default="")
    status: Mapped[str] = mapped_column(String(24), default="new", server_default="new")
    admin_note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ModelPricing(Base):
    """Configurable per-1M-token USD pricing table for FinOps cost & routing-savings telemetry."""

    __tablename__ = "model_pricing"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    model_pattern: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(120), default="", server_default="")
    input_usd_per_1m: Mapped[float] = mapped_column(Float, default=0.0, server_default="0")
    output_usd_per_1m: Mapped[float] = mapped_column(Float, default=0.0, server_default="0")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    updated_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ScheduledTask(Base):
    """User-defined scheduled AI prompt / recurring task."""

    __tablename__ = "scheduled_tasks"
    __table_args__ = (
        Index("ix_scheduled_tasks_user_created", "user_id", "created_at"),
        Index("ix_scheduled_tasks_due", "enabled", "status", "next_run_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True, index=True
    )
    target_mode: Mapped[str] = mapped_column(String(16), default="dedicated", server_default="dedicated")
    name: Mapped[str] = mapped_column(String(120))
    prompt: Mapped[str] = mapped_column(Text)
    schedule_type: Mapped[str] = mapped_column(String(16))
    schedule_config: Mapped[dict] = mapped_column(JSONB, default=dict)
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Shanghai", server_default="Asia/Shanghai")
    model_route: Mapped[str] = mapped_column(String(16), default="auto", server_default="auto")
    skill_names: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true", index=True)
    status: Mapped[str] = mapped_column(String(24), default="active", server_default="active", index=True)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_run_status: Mapped[str | None] = mapped_column(String(24), nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    run_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    max_runs: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source: Mapped[str] = mapped_column(String(24), default="manual", server_default="manual")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    runs: Mapped[list["ScheduledTaskRun"]] = relationship(
        back_populates="task", cascade="all, delete-orphan", order_by="ScheduledTaskRun.started_at.desc()"
    )


class ScheduledTaskRun(Base):
    """Execution history record for a scheduled task."""

    __tablename__ = "scheduled_task_runs"
    __table_args__ = (
        Index("ix_scheduled_task_runs_task_started", "task_id", "started_at"),
        Index("ix_scheduled_task_runs_user_started", "user_id", "started_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    task_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("scheduled_tasks.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True
    )
    assistant_message_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    run_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    trigger_type: Mapped[str] = mapped_column(String(16), default="scheduled", server_default="scheduled")
    status: Mapped[str] = mapped_column(String(24), default="queued", server_default="queued", index=True)
    scheduled_for: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    tokens_used: Mapped[int] = mapped_column(Integer, default=0, server_default="0")

    task: Mapped[ScheduledTask] = relationship(back_populates="runs")


class ScheduledTaskPendingProposal(Base):
    """Agent-proposed scheduled task change waiting for explicit user confirmation."""

    __tablename__ = "scheduled_task_pending_proposals"
    __table_args__ = (Index("ix_schedule_pending_user_status", "user_id", "status", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    target_task_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    action: Mapped[str] = mapped_column(String(24), default="create", server_default="create")
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)
    reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="pending", server_default="pending", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AiPostDailyRun(Base):
    """Per-user per-local-date idempotency record for daily AI auto-posting."""

    __tablename__ = "ai_post_daily_runs"
    __table_args__ = (
        UniqueConstraint("user_id", "local_date", name="uq_ai_post_daily_runs_user_date"),
        Index("ix_ai_post_daily_runs_user_date", "user_id", "local_date"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    local_date: Mapped[date] = mapped_column(Date)
    tier: Mapped[str] = mapped_column(String(16), default="free", server_default="free")
    memory_entry_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    active_collection_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    target_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    generated_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    status: Mapped[str] = mapped_column(String(32), default="running", server_default="running")
    tokens_used: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Post(Base):
    """Private feed post (AI-generated or user-authored), strictly visible only to its owner."""

    __tablename__ = "posts"
    __table_args__ = (
        Index("ix_posts_user_created", "user_id", "created_at"),
        Index("ix_posts_user_author_created", "user_id", "author_type", "created_at"),
        Index("ix_posts_user_bookmarked", "user_id", "is_bookmarked", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    author_type: Mapped[str] = mapped_column(String(16), default="ai", server_default="ai")
    post_kind: Mapped[str] = mapped_column(String(24), default="opinion", server_default="opinion")
    title: Mapped[str] = mapped_column(String(120), default="", server_default="")
    content: Mapped[str] = mapped_column(Text)
    tags: Mapped[list[str]] = mapped_column(JSONB, default=list, server_default=text("'[]'::jsonb"))
    web_sources: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list, server_default=text("'[]'::jsonb"))
    source_collection_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("memory_collections.id", ondelete="SET NULL"), nullable=True
    )
    source_collection_name: Mapped[str | None] = mapped_column(String(80), nullable=True)
    source_memory_ids: Mapped[list[str]] = mapped_column(JSONB, default=list, server_default=text("'[]'::jsonb"))
    memory_entry_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("memory_entries.id", ondelete="SET NULL"), nullable=True
    )
    is_liked: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    ai_liked: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    is_bookmarked: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True
    )
    daily_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("ai_post_daily_runs.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    comments: Mapped[list["PostComment"]] = relationship(
        back_populates="post",
        cascade="all, delete-orphan",
        order_by="PostComment.created_at",
        lazy="noload",
    )


class PostComment(Base):
    """Comment on a private post, supporting both user and AI comments with threaded replies."""

    __tablename__ = "post_comments"
    __table_args__ = (Index("ix_post_comments_post_created", "post_id", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    post_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("posts.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    author_type: Mapped[str] = mapped_column(String(16), default="user", server_default="user")
    content: Mapped[str] = mapped_column(Text)
    reply_to_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("post_comments.id", ondelete="SET NULL"), nullable=True
    )
    ai_liked: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    post: Mapped[Post] = relationship(back_populates="comments")


class AiPostPendingInteraction(Base):
    """Delayed AI engagement job for realistic non-instant likes and comments on user posts/comments."""

    __tablename__ = "ai_post_pending_interactions"
    __table_args__ = (
        Index("ix_ai_post_interactions_user", "user_id"),
        Index("ix_ai_post_interactions_due", "status", "scheduled_for"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    post_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("posts.id", ondelete="CASCADE"))
    trigger_comment_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("post_comments.id", ondelete="CASCADE"), nullable=True
    )
    kind: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(24), default="pending", server_default="pending")
    scheduled_for: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    tokens_used: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())