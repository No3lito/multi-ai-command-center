"""Provider-neutral request/response types and the adapter interface.

Adapters only translate. They never check budgets or permissions: every call goes through
command_center.providers.model_port.ModelPort, which reserves money before paid requests.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Protocol

Role = Literal["user", "assistant"]
ErrorCode = Literal[
    "auth_failed",
    "rate_limited",
    "context_overflow",
    "content_refused",
    "unavailable",
    "bad_request",
    "timeout",
]


@dataclass(frozen=True)
class ChatMessage:
    role: Role
    content: str


@dataclass(frozen=True)
class ChatRequest:
    model: str
    system: str
    messages: list[ChatMessage]
    max_output_tokens: int

    def prompt_chars(self) -> int:
        return len(self.system) + sum(len(m.content) for m in self.messages)

    def prompt_bytes(self) -> int:
        """UTF-8 size of the prompt. A token is never smaller than one byte in practice, so this
        bounds the input-token count from above for any language or emoji."""
        return len(self.system.encode("utf-8")) + sum(len(m.content.encode("utf-8")) for m in self.messages)


@dataclass(frozen=True)
class ChatResponse:
    text: str
    input_tokens: int
    output_tokens: int
    model: str
    request_id: str | None = None
    stop_reason: str | None = None
    # False when the provider did not report token usage. The budget then counts the full
    # reservation as spent instead of zero.
    usage_reported: bool = True


@dataclass(frozen=True)
class Capabilities:
    streaming: bool = False
    tool_calling: bool = False
    structured_output: bool = False
    extensions: frozenset[str] = field(default_factory=frozenset)


class ProviderError(Exception):
    """Normalized provider failure.

    maybe_billed: True when the request may have reached the provider and been charged
    (timeouts, dropped connections, server errors). The budget then keeps the reservation
    instead of releasing it, so spend is never under-counted.
    """

    def __init__(self, code: ErrorCode, message: str, *, retryable: bool, maybe_billed: bool) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable
        self.maybe_billed = maybe_billed


class ProviderAdapter(Protocol):
    id: str
    simulated: bool

    def capabilities(self, model: str) -> Capabilities: ...

    async def generate(self, req: ChatRequest) -> ChatResponse: ...
