import re
import uuid
from datetime import date, datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator

PHONE_RE = re.compile(r"^[+\d\s\-()]{5,32}$")

EmailStr = Annotated[
    str, StringConstraints(strip_whitespace=True, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$", max_length=320)
]
UsernameStr = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)
]
EmailCodePurpose = Literal["register", "login", "reset_password"]


def _validate_username_no_at(value: str) -> str:
    if "@" in value:
        raise ValueError("用户名不能包含 @ 符号")
    return value


class EmailCodeRequest(BaseModel):
    email: EmailStr
    purpose: EmailCodePurpose


class EmailCodeResponse(BaseModel):
    message: str
    expires_in: int
    cooldown: int


class RegisterRequest(BaseModel):
    email: EmailStr
    code: str = Field(min_length=4, max_length=12)
    password: str = Field(min_length=8, max_length=128)
    display_name: UsernameStr

    @field_validator("display_name")
    @classmethod
    def check_display_name(cls, v: str) -> str:
        return _validate_username_no_at(v)


class LoginRequest(BaseModel):
    identifier: str | None = Field(default=None, max_length=320)
    email: str | None = Field(default=None, max_length=320)
    password: str

    @model_validator(mode="after")
    def resolve_identifier(self) -> "LoginRequest":
        raw = self.identifier if self.identifier is not None else self.email
        cleaned = (raw or "").strip()
        if not cleaned:
            raise ValueError("请输入邮箱或用户名")
        self.identifier = cleaned
        return self

    @property
    def login_id(self) -> str:
        return self.identifier or ""


class EmailCodeLoginRequest(BaseModel):
    email: EmailStr
    code: str = Field(min_length=4, max_length=12)


class RefreshRequest(BaseModel):
    refresh_token: str | None = None


class ResetPasswordRequest(BaseModel):
    email: EmailStr
    code: str = Field(min_length=4, max_length=12)
    new_password: str = Field(min_length=8, max_length=128)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    display_name: str
    avatar_url: str | None = None
    assistant_name: str = "Whitz"
    assistant_avatar_url: str | None = None
    bio: str = ""
    gender: str | None = None
    birthday: date | None = None
    phone: str | None = None
    location: str | None = None
    occupation: str | None = None
    website: str | None = None
    preferred_language: str = "zh-CN"
    timezone: str = "Asia/Shanghai"
    role: str
    is_active: bool
    persona: str
    profile_context_enabled: bool = False
    profile_context_consented_at: datetime | None = None
    memory_enabled: bool = True
    memory_consented_at: datetime | None = None
    memory_require_confirm: bool = False
    ai_reactions_enabled: bool = True
    email_verified_at: datetime | None = None
    membership_tier: str
    membership_expires_at: datetime | None
    created_at: datetime


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    refresh_expires_in: int
    user: UserOut


class UpdateProfileRequest(BaseModel):
    display_name: UsernameStr | None = None
    avatar_url: str | None = Field(default=None, max_length=500)
    bio: str | None = Field(default=None, max_length=300)
    gender: str | None = Field(default=None, max_length=40)
    birthday: date | None = None
    phone: str | None = Field(default=None, max_length=32)
    location: str | None = Field(default=None, max_length=80)
    occupation: str | None = Field(default=None, max_length=80)
    website: str | None = Field(default=None, max_length=255)
    preferred_language: str | None = Field(default=None, max_length=16)
    timezone: str | None = Field(default=None, max_length=64)

    @field_validator("display_name")
    @classmethod
    def check_display_name(cls, v: str | None) -> str | None:
        if v is None:
            return None
        return _validate_username_no_at(v)

    @field_validator("avatar_url")
    @classmethod
    def check_avatar_url(cls, v: str | None) -> str | None:
        if v is None:
            return None
        cleaned = v.strip()
        if not cleaned:
            return None
        if not (cleaned.startswith("https://") or cleaned.startswith("http://")):
            raise ValueError("头像链接必须以 http:// 或 https:// 开头")
        return cleaned

    @field_validator("website")
    @classmethod
    def check_website(cls, v: str | None) -> str | None:
        if v is None:
            return None
        cleaned = v.strip()
        if not cleaned:
            return None
        if not (cleaned.startswith("https://") or cleaned.startswith("http://")):
            raise ValueError("个人主页需以 http:// 或 https:// 开头")
        return cleaned

    @field_validator("phone")
    @classmethod
    def check_phone(cls, v: str | None) -> str | None:
        if v is None:
            return None
        cleaned = v.strip()
        if not cleaned:
            return None
        if not PHONE_RE.match(cleaned):
            raise ValueError("请输入有效的联系电话")
        return cleaned

    @field_validator("bio", "gender", "location", "occupation", "preferred_language", "timezone")
    @classmethod
    def strip_optional_text(cls, v: str | None) -> str | None:
        if v is None:
            return None
        return v.strip()


class AvatarUploadRequest(BaseModel):
    data_url: str = Field(min_length=32, max_length=1_600_000)


class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str = Field(min_length=8, max_length=128)


class UpdatePersonaRequest(BaseModel):
    persona: str = Field(max_length=4000)


class UpdateAssistantRequest(BaseModel):
    assistant_name: str | None = Field(default=None, max_length=80)


ConversationKind = Literal["main", "side"]


class ConversationCreate(BaseModel):
    title: str = Field(default="新旁聊", max_length=200)


class ConversationUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    is_pinned: bool | None = None


class MessageReactionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    message_id: uuid.UUID
    author_type: str
    reaction: str
    reason_code: str | None = None
    comment: str | None = None
    created_at: datetime


class MessageReactionCreateRequest(BaseModel):
    reaction: Literal["like", "love", "insightful", "celebrate", "dislike"]
    reason_code: str | None = Field(default=None, max_length=40)
    comment: str | None = Field(default=None, max_length=500)


class UserFeedbackCreateRequest(BaseModel):
    rating: int = Field(ge=1, le=5)
    category: Literal["general", "quality", "speed", "ui", "feature", "bug"] = "general"
    content: str = Field(min_length=1, max_length=2000)


class UserFeedbackOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    rating: int
    sentiment: str
    category: str
    content: str
    status: str
    admin_note: str | None = None
    created_at: datetime
    updated_at: datetime


class UpdateAiReactionsRequest(BaseModel):
    ai_reactions_enabled: bool


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    role: str
    content: str
    tool_name: str | None
    tool_payload: dict | None
    status: str
    run_id: str | None
    created_at: datetime
    reactions: list[MessageReactionOut] = Field(default_factory=list)


class ConversationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    kind: ConversationKind = "side"
    title: str
    is_pinned: bool = False
    pinned_at: datetime | None = None
    is_scheduled: bool = False
    plan: dict | None
    active_run_id: str | None
    active_run_status: str | None
    pending_control: dict | None = None
    created_at: datetime
    updated_at: datetime
    last_message_at: datetime | None


class ConversationDetail(ConversationOut):
    messages: list[MessageOut]


class ConversationSearchHit(BaseModel):
    conversation_id: uuid.UUID
    conversation_kind: ConversationKind = "side"
    conversation_title: str
    is_scheduled: bool = False
    message_id: uuid.UUID | None = None
    role: str | None = None
    snippet: str
    match_in: Literal["title", "message"]
    created_at: datetime


ModelRouteType = Literal["auto", "default", "fast", "reasoning", "vision"]
RagModeType = Literal["auto", "files_only", "off"]


class RagScopeRequest(BaseModel):
    mode: RagModeType = "auto"
    file_ids: list[uuid.UUID] = Field(default_factory=list, max_length=20)
    include_memory: bool = True
    include_chats: bool = True


class SendMessageRequest(BaseModel):
    content: str = Field(min_length=1, max_length=32000)
    file_ids: list[uuid.UUID] = Field(default_factory=list, max_length=20)
    skill_names: list[str] = Field(default_factory=list, max_length=10)
    model_route: ModelRouteType = "auto"
    rag_scope: RagScopeRequest | None = None


class EditMessageRequest(BaseModel):
    content: str = Field(min_length=1, max_length=32000)
    file_ids: list[uuid.UUID] = Field(default_factory=list, max_length=20)
    skill_names: list[str] = Field(default_factory=list, max_length=10)
    model_route: ModelRouteType = "auto"
    rag_scope: RagScopeRequest | None = None


class RegenerateMessageRequest(BaseModel):
    model_route: ModelRouteType = "auto"
    rag_scope: RagScopeRequest | None = None


class FilePresignRequest(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    mime_type: str = Field(default="", max_length=128)
    size_bytes: int = Field(ge=1)


class FilePresignOut(BaseModel):
    file_id: uuid.UUID
    filename: str
    ext: str
    category: str
    mime_type: str
    size_bytes: int
    upload_url: str
    method: str = "PUT"
    headers: dict[str, str]
    expires_in: int


class FileCompleteRequest(BaseModel):
    etag: str | None = Field(default=None, max_length=128)


class ConversationFileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    conversation_id: uuid.UUID | None = None
    conversation_title: str | None = None
    conversation_kind: str | None = None
    filename: str
    ext: str
    mime_type: str
    category: str
    size_bytes: int
    status: str
    index_status: str = "ready"
    indexed_chunks: int = 0
    summary: str = ""
    index_error: str | None = None
    indexed_at: datetime | None = None
    source: str = "user"
    is_global: bool = True
    message_id: uuid.UUID | None = None
    qa_snippet: str | None = None
    turn_role: str | None = None
    preview_url: str | None = None
    thumb_url: str | None = None
    preview_expires_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class LibraryFileOut(ConversationFileOut):
    pass


class CreateTextFileRequest(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    content: str = Field(default="", max_length=2 * 1024 * 1024)
    overwrite: bool = False


class UpdateTextFileContentRequest(BaseModel):
    content: str = Field(default="", max_length=2 * 1024 * 1024)


class RenameConversationFileRequest(BaseModel):
    filename: str = Field(min_length=1, max_length=255)


class LibraryFileUpdateRequest(BaseModel):
    is_global: bool | None = None
    filename: str | None = Field(default=None, min_length=1, max_length=255)


class AttachLibraryFilesRequest(BaseModel):
    file_ids: list[uuid.UUID] = Field(min_length=1, max_length=20)


class FileDownloadUrlOut(BaseModel):
    url: str
    expires_in: int


class ChatTicketRequest(BaseModel):
    action: Literal["send", "reconnect", "stop", "approval", "clarify"]
    nonce: str = Field(min_length=8, max_length=64)


class ChatTicketOut(BaseModel):
    ticket: str
    expires_in: int


class ApprovalRequest(BaseModel):
    request_id: str
    execution_generation: int
    choice: str = Field(pattern="^(once|deny)$")


class ClarifyAnswerItem(BaseModel):
    id: str | None = None
    question: str | None = None
    selected: list[str] = Field(default_factory=list)
    text: str = Field(default="", max_length=4000)


class ClarifyRequest(BaseModel):
    request_id: str
    execution_generation: int
    answer: str = Field(default="", max_length=16000)
    answers: list[ClarifyAnswerItem] | None = None

    @model_validator(mode="after")
    def _ensure_non_empty_clarify(self) -> "ClarifyRequest":
        cleaned_answer = (self.answer or "").strip()
        if not cleaned_answer and self.answers:
            lines: list[str] = []
            for idx, item in enumerate(self.answers, start=1):
                parts = [*[s.strip() for s in item.selected if s.strip()]]
                if item.text.strip():
                    parts.append(item.text.strip())
                if not parts:
                    continue
                val = "；".join(parts)
                if item.question and item.question.strip():
                    lines.append(f"{idx}. {item.question.strip()}\n答：{val}")
                else:
                    lines.append(f"{idx}. {val}")
            cleaned_answer = "\n\n".join(lines).strip()
        if not cleaned_answer:
            raise ValueError("回答内容不能为空")
        self.answer = cleaned_answer
        return self


class CreditWindowOut(BaseModel):
    limit: int | None
    used: float
    remaining: float | None
    reset_at: str


class MembershipPlanOut(BaseModel):
    tier: str
    label: str
    weekly_credits: int
    five_hour_credits: int | None
    max_runs_per_user: int
    chat_per_minute: int
    run_max_seconds: int
    max_tool_iterations: int = 30
    summary: str


class CreditStatusOut(BaseModel):
    tier: str
    tier_label: str
    expires_at: str | None
    anchor_at: str
    tokens_per_credit: int
    weekly: CreditWindowOut
    five_hour: CreditWindowOut
    remaining: float
    overdrawn: bool
    plan: MembershipPlanOut
    plans: list[MembershipPlanOut]


class RedeemRequest(BaseModel):
    code: str = Field(min_length=4, max_length=32)


class CreditSummaryOut(BaseModel):
    tier: str
    tier_label: str
    expires_at: datetime | None = None
    remaining: float
    weekly_used: float
    weekly_limit: int
    five_hour_used: float
    five_hour_limit: int | None
    week_reset_at: str
    five_hour_reset_at: str
    overdrawn: bool


class AdminUserUpdate(BaseModel):
    is_active: bool | None = None
    role: str | None = Field(default=None, pattern="^(user|admin)$")


class AdminMembershipUpdate(BaseModel):
    tier: str = Field(pattern="^(free|plus|pro)$")
    expires_at: datetime | None = None


class AdminCreditAdjust(BaseModel):
    credits: int = Field(ge=-100000, le=100000)
    note: str | None = Field(default=None, max_length=200)


class InviteCodeCreate(BaseModel):
    tier: str = Field(pattern="^(plus|pro)$")
    duration_days: int = Field(default=30, ge=1, le=365)
    max_uses: int = Field(default=1, ge=1, le=1000)
    expires_at: datetime | None = None
    note: str | None = Field(default=None, max_length=200)


class InviteCodeUpdate(BaseModel):
    is_active: bool


class InviteCodeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code: str
    tier: str
    duration_days: int
    max_uses: int
    used_count: int
    expires_at: datetime | None
    note: str | None
    is_active: bool
    created_at: datetime


class AdminUserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    display_name: str
    avatar_url: str | None = None
    assistant_name: str = "Whitz"
    assistant_avatar_url: str | None = None
    bio: str = ""
    gender: str | None = None
    birthday: date | None = None
    phone: str | None = None
    location: str | None = None
    occupation: str | None = None
    website: str | None = None
    preferred_language: str = "zh-CN"
    timezone: str = "Asia/Shanghai"
    role: str
    is_active: bool
    agent_namespace: str
    membership_tier: str
    membership_expires_at: datetime | None
    credits: CreditSummaryOut | None = None
    created_at: datetime


class ProfileContextUpdateRequest(BaseModel):
    enabled: bool
    consent: bool = False


class MemorySettingsUpdateRequest(BaseModel):
    enabled: bool | None = None
    require_confirm: bool | None = None
    consent: bool = False


class MemoryCollectionOut(BaseModel):
    id: str
    slug: str
    name: str
    description: str = ""
    kind: str = "custom"
    enabled: bool = True
    entry_count: int = 0
    char_count: int = 0
    char_limit: int = 12000
    max_entries: int = 200
    sort_order: int = 100
    created_at: datetime | None = None
    updated_at: datetime | None = None


class MemoryCollectionCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    slug: str | None = Field(default=None, max_length=64)
    description: str = Field(default="", max_length=300)
    char_limit: int = Field(default=12000, ge=2000, le=50000)

    @field_validator("name")
    @classmethod
    def check_name(cls, v: str) -> str:
        cleaned = v.strip()
        if not cleaned:
            raise ValueError("记忆集名称不能为空")
        return cleaned


class MemoryCollectionUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    description: str | None = Field(default=None, max_length=300)
    enabled: bool | None = None
    char_limit: int | None = Field(default=None, ge=2000, le=50000)
    sort_order: int | None = Field(default=None, ge=0, le=10000)


class MemoryEntryOut(BaseModel):
    id: str
    collection_id: str | None = None
    collection_name: str | None = None
    target: str = "memory"
    title: str = ""
    content: str
    tags: list[str] = Field(default_factory=list)
    source: str = "manual"
    is_pinned: bool = False
    priority: int = 2
    access_count: int = 0
    last_accessed_at: datetime | None = None
    supersedes_id: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class MemoryEntryCreateRequest(BaseModel):
    target: str = Field(default="memory", max_length=64)
    collection_id: str | None = None
    title: str = Field(default="", max_length=120)
    content: str = Field(min_length=1, max_length=4000)
    tags: list[str] = Field(default_factory=list)
    is_pinned: bool = False
    priority: int = Field(default=2, ge=1, le=3)

    @field_validator("content")
    @classmethod
    def check_content(cls, v: str) -> str:
        cleaned = v.strip()
        if not cleaned:
            raise ValueError("记忆内容不能为空")
        return cleaned


class MemoryEntryUpdateRequest(BaseModel):
    content: str | None = Field(default=None, min_length=1, max_length=4000)
    target: str | None = Field(default=None, max_length=64)
    collection_id: str | None = None
    title: str | None = Field(default=None, max_length=120)
    tags: list[str] | None = None
    is_pinned: bool | None = None
    priority: int | None = Field(default=None, ge=1, le=3)

    @field_validator("content")
    @classmethod
    def check_content(cls, v: str | None) -> str | None:
        if v is None:
            return None
        cleaned = v.strip()
        if not cleaned:
            raise ValueError("记忆内容不能为空")
        return cleaned


class ConversationEpisodeOut(BaseModel):
    id: str
    conversation_id: str
    conversation_kind: str = "main"
    episode_index: int = 1
    topic: str = ""
    summary: str = ""
    key_facts: list[str] = Field(default_factory=list)
    entities: list[str] = Field(default_factory=list)
    start_msg_id: str | None = None
    end_msg_id: str | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None
    message_count: int = 0
    created_at: datetime | None = None


class ConversationContextStateOut(BaseModel):
    conversation_id: str
    conversation_kind: str
    working_state: dict[str, Any] | None = None
    rolling_summary: str | None = None
    working_state_updated_at: datetime | None = None
    episodes: list[ConversationEpisodeOut] = Field(default_factory=list)
    pinned_memories_count: int = 0


class WorkingStateUpdateRequest(BaseModel):
    working_state: dict[str, Any]


class MemoryPendingOut(BaseModel):
    id: str
    collection_id: str | None = None
    target: str = "memory"
    title: str = ""
    tags: list[str] = Field(default_factory=list)
    action: str = "add"
    content: str
    old_content: str | None = None
    conversation_id: uuid.UUID | None = None
    created_at: datetime | None = None


class MemoryPendingResolveRequest(BaseModel):
    action: Literal["approve", "reject"]
    content: str | None = Field(default=None, max_length=4000)


class MemorySearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    collection: str | None = Field(default=None, max_length=64)
    limit: int = Field(default=12, ge=1, le=50)


class MemorySearchHitOut(BaseModel):
    id: str
    collection_id: str | None = None
    target: str = "memory"
    collection_name: str = ""
    title: str = ""
    content: str
    tags: list[str] = Field(default_factory=list)
    source: str = "manual"
    score: float = 0.0


class MemorySearchResponse(BaseModel):
    query: str
    collection: str | None = None
    count: int = 0
    results: list[MemorySearchHitOut] = Field(default_factory=list)


class MemoryOverviewOut(BaseModel):
    memory_enabled: bool
    memory_consented_at: datetime | None = None
    memory_require_confirm: bool
    collections: list[MemoryCollectionOut] = Field(default_factory=list)
    entries: list[MemoryEntryOut] = Field(default_factory=list)
    pending: list[MemoryPendingOut] = Field(default_factory=list)
    char_count: int = 0
    char_limit: int = 12000
    memory_char_count: int = 0
    memory_char_limit: int = 12000
    user_char_count: int = 0
    user_char_limit: int = 8000
    total_char_count: int = 0
    total_char_limit: int = 200000
    collection_limit: int = 50
    pinned_count: int = 0
    pinned_limit: int = 10


class SkillOut(BaseModel):
    name: str
    title: str | None = None
    description: str = ""
    category: str | None = None
    enabled: bool = True
    source: str = "custom"
    repo_url: str | None = None
    content: str | None = None
    tags: list[str] = Field(default_factory=list)
    updated_at: datetime | None = None


class SkillCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    description: str = Field(default="", max_length=500)
    content: str = Field(min_length=1, max_length=64000)
    category: str | None = Field(default=None, max_length=64)
    enabled: bool = True

    @field_validator("name")
    @classmethod
    def check_skill_name(cls, v: str) -> str:
        cleaned = v.strip()
        if not cleaned or "/" in cleaned or "\\" in cleaned or ".." in cleaned:
            raise ValueError("技能名称无效")
        return cleaned


class SkillToggleRequest(BaseModel):
    enabled: bool


class SkillGithubPreviewRequest(BaseModel):
    url: str = Field(min_length=1, max_length=500)
    ref: str | None = Field(default=None, max_length=120)
    path: str | None = Field(default=None, max_length=300)


class SkillGithubPreviewOut(BaseModel):
    name: str
    description: str = ""
    content: str
    repo_url: str
    ref: str | None = None
    path: str | None = None


class SkillGithubInstallRequest(BaseModel):
    url: str = Field(min_length=1, max_length=500)
    name: str | None = Field(default=None, max_length=80)
    ref: str | None = Field(default=None, max_length=120)
    path: str | None = Field(default=None, max_length=300)
    enabled: bool = True


class SkillPendingOut(BaseModel):
    id: str
    name: str
    description: str = ""
    content: str
    action: str = "create"
    source: str = "agent"
    conversation_id: uuid.UUID | None = None
    created_at: datetime | None = None


class SkillPendingResolveRequest(BaseModel):
    action: Literal["approve", "reject"]
    content: str | None = Field(default=None, max_length=64000)
    enabled: bool = True


class UserSessionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    session_id: uuid.UUID
    user_agent: str | None = None
    client_ip: str | None = None
    last_used_at: datetime | None = None
    created_at: datetime
    expires_at: datetime
    is_current: bool = False


class AdminLedgerItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: uuid.UUID
    created_at: datetime
    tokens: int
    credits: float = 0.0
    kind: str
    tier: str | None = None
    conversation_id: uuid.UUID | None = None
    message_id: uuid.UUID | None = None
    actor_user_id: uuid.UUID | None = None
    actor_email: str | None = None
    note: str | None = None


class InviteRedemptionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code_id: uuid.UUID
    code: str | None = None
    user_id: uuid.UUID
    user_email: str | None = None
    tier: str
    duration_days: int
    redeemed_at: datetime


class AdminUserDetailOut(AdminUserOut):
    persona: str = ""
    email_verified_at: datetime | None = None
    credit_anchor_at: datetime | None = None
    updated_at: datetime | None = None
    profile_context_enabled: bool = False
    profile_context_consented_at: datetime | None = None
    memory_enabled: bool = True
    memory_consented_at: datetime | None = None
    memory_require_confirm: bool = False
    memory_collection_count: int = 0
    memory_entry_count: int = 0
    conversation_count: int = 0
    message_count: int = 0
    file_count: int = 0
    total_tokens: int = 0
    total_messages: int = 0
    total_runs: int = 0
    active_sessions: list[UserSessionOut] = Field(default_factory=list)
    recent_ledger: list[AdminLedgerItemOut] = Field(default_factory=list)
    invite_redemptions: list[InviteRedemptionOut] = Field(default_factory=list)


class AdminAnalyticsDayOut(BaseModel):
    day: str
    messages: int = 0
    tokens: int = 0
    credits: float = 0.0
    runs: int = 0
    new_users: int = 0
    active_users: int = 0


class AdminAnalyticsTopUserOut(BaseModel):
    user_id: uuid.UUID
    email: str
    display_name: str
    membership_tier: str
    messages: int = 0
    tokens: int = 0
    credits: float = 0.0
    runs: int = 0


class AdminAnalyticsOut(BaseModel):
    days: int = 30
    start_day: str
    end_day: str
    tokens_per_credit: int = 5000
    daily: list[AdminAnalyticsDayOut] = Field(default_factory=list)
    top_users: list[AdminAnalyticsTopUserOut] = Field(default_factory=list)
    membership_distribution: dict[str, int] = Field(default_factory=dict)
    file_stats: dict[str, int] = Field(default_factory=dict)
    summary: dict[str, int | float] = Field(default_factory=dict)
    generated_at: datetime


ScheduleTypeLiteral = Literal["once", "interval", "daily", "weekly", "monthly", "cron"]
ScheduleTargetModeLiteral = Literal["dedicated", "main", "conversation"]
ScheduleModelRouteLiteral = Literal["auto", "default", "fast", "reasoning"]


class ScheduledTaskCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    prompt: str = Field(min_length=1, max_length=16000)
    schedule_type: ScheduleTypeLiteral
    schedule_config: dict[str, Any] = Field(default_factory=dict)
    timezone: str | None = Field(default=None, max_length=64)
    target_mode: ScheduleTargetModeLiteral = "dedicated"
    conversation_id: uuid.UUID | None = None
    model_route: ScheduleModelRouteLiteral = "auto"
    skill_names: list[str] = Field(default_factory=list, max_length=10)
    enabled: bool = True
    max_runs: int | None = Field(default=None, ge=1, le=10000)


class ScheduledTaskUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    prompt: str | None = Field(default=None, min_length=1, max_length=16000)
    schedule_type: ScheduleTypeLiteral | None = None
    schedule_config: dict[str, Any] | None = None
    timezone: str | None = Field(default=None, max_length=64)
    target_mode: ScheduleTargetModeLiteral | None = None
    conversation_id: uuid.UUID | None = None
    model_route: ScheduleModelRouteLiteral | None = None
    skill_names: list[str] | None = Field(default=None, max_length=10)
    enabled: bool | None = None
    max_runs: int | None = Field(default=None, ge=1, le=10000)


class SchedulePreviewRequest(BaseModel):
    schedule_type: ScheduleTypeLiteral
    schedule_config: dict[str, Any] = Field(default_factory=dict)
    timezone: str | None = Field(default=None, max_length=64)
    count: int = Field(default=5, ge=1, le=10)


class SchedulePreviewOut(BaseModel):
    valid: bool
    schedule_description: str = ""
    next_runs: list[datetime] = Field(default_factory=list)
    error: str | None = None


class ScheduledTaskRunOut(BaseModel):
    id: uuid.UUID
    task_id: uuid.UUID
    conversation_id: uuid.UUID | None = None
    assistant_message_id: uuid.UUID | None = None
    run_id: str | None = None
    trigger_type: str = "scheduled"
    status: str
    scheduled_for: datetime | None = None
    started_at: datetime
    finished_at: datetime | None = None
    summary: str | None = None
    error: str | None = None
    tokens_used: int = 0


class ScheduledTaskOut(BaseModel):
    id: uuid.UUID
    conversation_id: uuid.UUID | None = None
    target_mode: str = "dedicated"
    name: str
    prompt: str
    schedule_type: str
    schedule_config: dict[str, Any] = Field(default_factory=dict)
    schedule_description: str = ""
    timezone: str = "Asia/Shanghai"
    model_route: str = "auto"
    skill_names: list[str] = Field(default_factory=list)
    enabled: bool = True
    status: str = "active"
    next_run_at: datetime | None = None
    last_run_at: datetime | None = None
    last_run_status: str | None = None
    last_error: str | None = None
    run_count: int = 0
    consecutive_failures: int = 0
    max_runs: int | None = None
    source: str = "manual"
    created_at: datetime
    updated_at: datetime


class ScheduledTaskDetailOut(ScheduledTaskOut):
    runs: list[ScheduledTaskRunOut] = Field(default_factory=list)


class ScheduledTaskPendingOut(BaseModel):
    id: str
    target_task_id: str | None = None
    conversation_id: uuid.UUID | None = None
    action: str = "create"
    payload: dict[str, Any] = Field(default_factory=dict)
    schedule_description: str = ""
    reason: str | None = None
    status: str = "pending"
    created_at: datetime | None = None


class ScheduledTaskPendingResolveRequest(BaseModel):
    action: Literal["approve", "reject"]


class ScheduleQuotaOut(BaseModel):
    tier: str
    max_active_tasks: int
    active_count: int
    min_interval_minutes: int


class ScheduleOverviewOut(BaseModel):
    tasks: list[ScheduledTaskOut] = Field(default_factory=list)
    pending: list[ScheduledTaskPendingOut] = Field(default_factory=list)
    quota: ScheduleQuotaOut
