"""Anthropic Claude adapter (official `anthropic` SDK, Messages API)."""

from __future__ import annotations

from typing import Literal, cast

import anthropic
import httpx2
from anthropic.types import MessageParam, OutputConfigParam, TextBlock

from command_center.providers.base import Capabilities, ChatRequest, ChatResponse, ErrorCode, ProviderError

Effort = Literal["low", "medium", "high", "xhigh", "max"]


class AnthropicAdapter:
    id = "anthropic"
    simulated = False

    def __init__(
        self,
        api_key: str,
        *,
        http_client: httpx2.AsyncClient | None = None,
        timeout: float = 90.0,
        effort: str | None = "medium",
    ) -> None:
        # Claude 5.5 models think before answering by default, and thinking tokens count toward
        # max_tokens. "medium" keeps thinking proportionate so the answer fits; None leaves
        # the model's own default (Sonnet 5.5: "high").
        self.effort = effort
        self._output_config: OutputConfigParam | anthropic.Omit = (
            {"effort": cast(Effort, effort)} if effort else anthropic.omit
        )
        # max_retries=0: retries would re-send a paid request outside our budget reservation.
        self._client = anthropic.AsyncAnthropic(
            api_key=api_key, http_client=http_client, timeout=timeout, max_retries=0
        )

    def capabilities(self, model: str) -> Capabilities:
        return Capabilities(streaming=True, tool_calling=True, structured_output=True)

    async def generate(self, req: ChatRequest) -> ChatResponse:
        try:
            resp = await self._client.messages.create(
                model=req.model,
                max_tokens=req.max_output_tokens,
                system=req.system,
                messages=[_message(m.role, m.content) for m in req.messages],
                output_config=self._output_config,
                timeout=req.timeout_seconds if req.timeout_seconds else anthropic.NOT_GIVEN,
            )
        except anthropic.AuthenticationError as exc:
            raise ProviderError(
                "auth_failed", "Anthropic rejected the API key", retryable=False, maybe_billed=False
            ) from exc
        except anthropic.PermissionDeniedError as exc:
            raise ProviderError(
                "auth_failed",
                "Anthropic API key lacks permission for this model",
                retryable=False,
                maybe_billed=False,
            ) from exc
        except anthropic.RateLimitError as exc:
            raise ProviderError(
                "rate_limited", "Anthropic rate limit reached", retryable=True, maybe_billed=False
            ) from exc
        except anthropic.BadRequestError as exc:
            text = str(exc).lower()
            code: ErrorCode = "context_overflow" if "too long" in text or "context" in text else "bad_request"
            raise ProviderError(
                code, f"Anthropic rejected the request: {_short(exc)}", retryable=False, maybe_billed=False
            ) from exc
        except anthropic.NotFoundError as exc:
            raise ProviderError(
                "bad_request", f"Unknown Anthropic model: {req.model}", retryable=False, maybe_billed=False
            ) from exc
        except (anthropic.APITimeoutError, anthropic.APIConnectionError) as exc:
            raise ProviderError(
                "unavailable", "Anthropic did not respond in time", retryable=True, maybe_billed=True
            ) from exc
        except anthropic.APIStatusError as exc:
            raise ProviderError(
                "unavailable",
                f"Anthropic error {exc.status_code}",
                retryable=True,
                maybe_billed=exc.status_code >= 500,
            ) from exc

        text = "".join(block.text for block in resp.content if isinstance(block, TextBlock))
        if resp.stop_reason == "refusal" and not text:
            raise ProviderError(
                "content_refused", "Claude declined to answer", retryable=False, maybe_billed=True
            )
        return ChatResponse(
            text=text,
            input_tokens=resp.usage.input_tokens
            + (resp.usage.cache_read_input_tokens or 0)
            + (resp.usage.cache_creation_input_tokens or 0),
            output_tokens=resp.usage.output_tokens,
            model=resp.model,
            request_id=resp.id,
            stop_reason=resp.stop_reason,
            truncated=resp.stop_reason == "max_tokens",
        )


def _message(role: str, content: str) -> MessageParam:
    if role == "assistant":
        return {"role": "assistant", "content": content}
    return {"role": "user", "content": content}


def _short(exc: Exception) -> str:
    return str(exc)[:200]
