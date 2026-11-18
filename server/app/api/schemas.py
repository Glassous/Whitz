import re
import uuid
from datetime import date, datetime
from typing import Annotated, Literal

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
    memory_enabled: bool = False
    memory_consented_at: datetime | None = None
    memory_require_confirm: bool = True
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


class ConversationCreate(BaseModel):
    title: str = Field(default="新对话", max_length=200)


class ConversationUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    is_pinned: bool | None = None


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    role: str
    content: str
    tool_name: str | None
    tool_payload: dict | None
    status: str
    hermes_run_id: str | None
    created_at: datetime


class ConversationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    is_pinned: bool = False
    pinned_at: datetime | None = None
    plan: dict | None
    active_run_id: str | None
    active_run_status: str | None
    created_at: datetime
    updated_at: datetime
    last_message_at: datetime | None


class ConversationDetail(ConversationOut):
    messages: list[MessageOut]


class ConversationSearchHit(BaseModel):
    conversation_id: uuid.UUID
    conversation_title: str
    message_id: uuid.UUID | None = None
    role: str | None = None
    snippet: str
    match_in: Literal["title", "message"]
    created_at: datetime


class SendMessageRequest(BaseModel):
    content: str = Field(min_length=1, max_length=32000)
    file_ids: list[uuid.UUID] = Field(default_factory=list, max_length=20)
    skill_names: list[str] = Field(default_factory=list, max_length=10)


class EditMessageRequest(BaseModel):
    content: str = Field(min_length=1, max_length=32000)
    file_ids: list[uuid.UUID] = Field(default_factory=list, max_length=20)
    skill_names: list[str] = Field(default_factory=list, max_length=10)


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
    filename: str
    ext: str
    mime_type: str
    category: str
    size_bytes: int
    status: str
    source: str = "user"
    is_global: bool = False
    message_id: uuid.UUID | None = None
    preview_url: str | None = None
    thumb_url: str | None = None
    preview_expires_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class LibraryFileOut(ConversationFileOut):
    conversation_title: str | None = None


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


class ClarifyRequest(BaseModel):
    request_id: str
    execution_generation: int
    answer: str = Field(min_length=1, max_length=4000)


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
    hermes_profile: str
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


class MemoryEntryOut(BaseModel):
    id: str
    target: str = "memory"
    content: str
    source: str = "manual"
    created_at: datetime | None = None
    updated_at: datetime | None = None


class MemoryEntryCreateRequest(BaseModel):
    target: Literal["memory", "user"] = "memory"
    content: str = Field(min_length=1, max_length=2000)

    @field_validator("content")
    @classmethod
    def check_content(cls, v: str) -> str:
        cleaned = v.strip()
        if not cleaned:
            raise ValueError("记忆内容不能为空")
        return cleaned


class MemoryEntryUpdateRequest(BaseModel):
    content: str = Field(min_length=1, max_length=2000)
    target: Literal["memory", "user"] | None = None

    @field_validator("content")
    @classmethod
    def check_content(cls, v: str) -> str:
        cleaned = v.strip()
        if not cleaned:
            raise ValueError("记忆内容不能为空")
        return cleaned


class MemoryPendingOut(BaseModel):
    id: str
    target: str = "memory"
    action: str = "add"
    content: str
    old_content: str | None = None
    conversation_id: uuid.UUID | None = None
    created_at: datetime | None = None


class MemoryPendingResolveRequest(BaseModel):
    action: Literal["approve", "reject"]
    content: str | None = Field(default=None, max_length=2000)


class MemoryOverviewOut(BaseModel):
    memory_enabled: bool
    memory_consented_at: datetime | None = None
    memory_require_confirm: bool
    entries: list[MemoryEntryOut] = Field(default_factory=list)
    pending: list[MemoryPendingOut] = Field(default_factory=list)
    char_count: int = 0
    char_limit: int = 2200
    memory_char_count: int = 0
    memory_char_limit: int = 2200
    user_char_count: int = 0
    user_char_limit: int = 1375


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
    memory_enabled: bool = False
    memory_consented_at: datetime | None = None
    memory_require_confirm: bool = True
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
