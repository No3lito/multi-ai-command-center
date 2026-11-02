"""CCMP v1 envelope (packages/protocol/ccmp.schema.json) and API request/response models."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

PRINCIPAL_ID = r"^(usr|agt|ext|sys)_[0-9a-f]{32}$"

MessageKind = Literal[
    "chat",
    "task.assign",
    "task.result",
    "task.status",
    "tool.request",
    "tool.result",
    "approval.request",
    "approval.decision",
    "artifact",
    "error",
    "control",
]
PrincipalKind = Literal["owner", "human", "agent", "external", "system"]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Sender(Strict):
    principal_id: str
    kind: PrincipalKind
    display_name: str


class Body(Strict):
    text: str = Field(max_length=32000)
    data: dict[str, Any] | None = None


class Usage(Strict):
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    cost_usd: float = Field(ge=0)


class CCMPMessage(Strict):
    id: str
    protocol: Literal["ccmp/1"] = "ccmp/1"
    seq: int = Field(ge=1)
    room_id: str
    thread_id: str | None = None
    sender: Sender
    kind: MessageKind
    reply_to: str | None = None
    mentions: list[str] = Field(default_factory=list)
    body: Body
    task_id: str | None = None
    correlation_id: str | None = None
    usage: Usage | None = None
    created_at: datetime


class PrincipalOut(Strict):
    id: str
    kind: PrincipalKind
    display_name: str


class RoomOut(Strict):
    id: str
    name: str
    created_at: datetime
    member_count: int
    last_seq: int


class RoomDetailOut(RoomOut):
    members: list[PrincipalOut]


class MessagePage(Strict):
    items: list[CCMPMessage]
    has_more: bool
    next_after_seq: int


class LoginIn(Strict):
    password: str = Field(min_length=1, max_length=512)


class LoginOut(Strict):
    principal: PrincipalOut


class RoomCreateIn(Strict):
    name: str

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        value = " ".join(value.split())
        if not 1 <= len(value) <= 80:
            raise ValueError("Room name must be 1 to 80 characters")
        return value


class ChatBodyIn(Strict):
    text: str

    @field_validator("text")
    @classmethod
    def _text(cls, value: str) -> str:
        value = value.strip()
        if not 1 <= len(value) <= 32000:
            raise ValueError("Message text must be 1 to 32000 characters")
        return value


class MessageCreateIn(Strict):
    kind: Literal["chat"] = "chat"
    body: ChatBodyIn
    reply_to: str | None = Field(default=None, pattern=r"^msg_[0-9a-f]{32}$")
    # Mentions are principal ids only (bounded size), never free text.
    mentions: list[Annotated[str, StringConstraints(pattern=PRINCIPAL_ID)]] = Field(
        default_factory=list, max_length=50
    )
    idempotency_key: str = Field(min_length=8, max_length=100, pattern=r"^[A-Za-z0-9._:-]+$")
