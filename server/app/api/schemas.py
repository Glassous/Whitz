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


class AdminUserUpdate(BaseModel):
    is_active: bool | None = None
    role: str | None = Field(default=None, pattern="^(user|admin)$")


class AdminUserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    display_name: str
    role: str
    is_active: bool
    hermes_profile: str
    created_at: datetime