import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

EmailStr = Annotated[str, StringConstraints(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$", max_length=320)]


class SecurityQuestionIn(BaseModel):
    question: str = Field(min_length=2, max_length=200)
    answer: str = Field(min_length=1, max_length=200)


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    display_name: str = Field(min_length=1, max_length=80)
    security_questions: list[SecurityQuestionIn] = Field(min_length=2, max_length=2)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str | None = None


class ResetPasswordRequest(BaseModel):
    email: EmailStr
    answers: list[str] = Field(min_length=2, max_length=2)
    new_password: str = Field(min_length=8, max_length=128)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    display_name: str
    role: str
    is_active: bool
    persona: str
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


class SecurityQuestionOut(BaseModel):
    position: int
    question: str


class UpdateProfileRequest(BaseModel):
    display_name: str = Field(min_length=1, max_length=80)


class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str = Field(min_length=8, max_length=128)


class UpdatePersonaRequest(BaseModel):
    persona: str = Field(max_length=4000)


class UpdateSecurityQuestionsRequest(BaseModel):
    password: str
    security_questions: list[SecurityQuestionIn] = Field(min_length=2, max_length=2)


class ConversationCreate(BaseModel):
    title: str = Field(default="新对话", max_length=200)


class ConversationUpdate(BaseModel):
    title: str = Field(min_length=1, max_length=200)


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
    role: str
    is_active: bool
    hermes_profile: str
    membership_tier: str
    membership_expires_at: datetime | None
    credits: CreditSummaryOut | None = None
    created_at: datetime