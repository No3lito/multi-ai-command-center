"""OpenAI and xAI (Grok) adapters: official `openai` SDK, Responses API.

xAI documents the OpenAI SDK pointed at https://api.x.ai/v1 with `responses.create` as its
preferred API (docs.x.ai/docs/guides/chat, checked Nov 2, 2026), so one implementation
serves both. The differences are isolated in class attributes on XAIAdapter.
"""

from __future__ import annotations

import httpx2
import openai
from openai.types.responses import EasyInputMessageParam, ResponseInputParam

from command_center.providers.base import Capabilities, ChatRequest, ChatResponse, ErrorCode, ProviderError


class OpenAIAdapter:
    id = "openai"
    label = "OpenAI"
    simulated = False
    # OpenAI documents `instructions` for the system prompt.
    system_as_message = False
    # OpenAI includes reasoning tokens in output_tokens.
    add_reasoning_tokens = False
    default_base_url: str | None = None

    def __init__(
        self,
        api_key: str,
        *,
        http_client: httpx2.AsyncClient | None = None,
        timeout: float = 90.0,
        base_url: str | None = None,
    ) -> None:
        # max_retries=0: retries would re-send a paid request outside our budget reservation.
        self._client = openai.AsyncOpenAI(
            api_key=api_key,
            http_client=http_client,
            timeout=timeout,
            max_retries=0,
            base_url=base_url or self.default_base_url,
        )

    def capabilities(self, model: str) -> Capabilities:
        return Capabilities(streaming=True, tool_calling=True, structured_output=True)

    async def generate(self, req: ChatRequest) -> ChatResponse:
        name = self.label
        messages: ResponseInputParam = [_input(m.role, m.content) for m in req.messages]
        with_system: ResponseInputParam = [_system(req.system), *messages]
        try:
            if self.system_as_message:
                resp = await self._client.responses.create(
                    model=req.model,
                    input=with_system,
                    max_output_tokens=req.max_output_tokens,
                    store=False,  # do not keep conversation state on the provider's side
                    timeout=req.timeout_seconds if req.timeout_seconds else openai.NOT_GIVEN,
                )
            else:
                resp = await self._client.responses.create(
                    model=req.model,
                    instructions=req.system,
                    input=messages,
                    max_output_tokens=req.max_output_tokens,
                    store=False,  # do not keep conversation state on the provider's side
                    timeout=req.timeout_seconds if req.timeout_seconds else openai.NOT_GIVEN,
                )
        except openai.AuthenticationError as exc:
            raise ProviderError(
                "auth_failed", f"{name} rejected the API key", retryable=False, maybe_billed=False
            ) from exc
        except openai.PermissionDeniedError as exc:
            raise ProviderError(
                "auth_failed",
                f"{name} API key lacks permission for this model",
                retryable=False,
                maybe_billed=False,
            ) from exc
        except openai.RateLimitError as exc:
            raise ProviderError(
                "rate_limited", f"{name} rate limit or quota reached", retryable=True, maybe_billed=False
            ) from exc
        except openai.BadRequestError as exc:
            text = str(exc).lower()
            code: ErrorCode = "context_overflow" if "context" in text or "too long" in text else "bad_request"
            raise ProviderError(
                code, f"{name} rejected the request: {str(exc)[:200]}", retryable=False, maybe_billed=False
            ) from exc
        except openai.NotFoundError as exc:
            raise ProviderError(
                "bad_request", f"Unknown {name} model: {req.model}", retryable=False, maybe_billed=False
            ) from exc
        except (openai.APITimeoutError, openai.APIConnectionError) as exc:
            raise ProviderError(
                "unavailable", f"{name} did not respond in time", retryable=True, maybe_billed=True
            ) from exc
        except openai.APIStatusError as exc:
            raise ProviderError(
                "unavailable",
                f"{name} error {exc.status_code}",
                retryable=True,
                maybe_billed=exc.status_code >= 500,
            ) from exc

        usage = resp.usage
        text = resp.output_text or ""
        if resp.status == "incomplete" and not text:
            reason = getattr(resp.incomplete_details, "reason", None) or "unknown"
            failure: ErrorCode = "content_refused" if reason == "content_filter" else "bad_request"
            raise ProviderError(
                failure, f"{name} returned no text ({reason})", retryable=False, maybe_billed=True
            )
        output_tokens = usage.output_tokens if usage else 0
        if usage is not None and self.add_reasoning_tokens:
            details = getattr(usage, "output_tokens_details", None)
            output_tokens += int(getattr(details, "reasoning_tokens", 0) or 0)
        return ChatResponse(
            text=text,
            input_tokens=usage.input_tokens if usage else 0,
            output_tokens=output_tokens,
            usage_reported=usage is not None,
            model=resp.model,
            request_id=resp.id,
            stop_reason=resp.status,
            truncated=resp.status == "incomplete"
            and getattr(resp.incomplete_details, "reason", None) == "max_output_tokens",
        )


class XAIAdapter(OpenAIAdapter):
    """Grok, via xAI's OpenAI-compatible Responses API."""

    id = "xai"
    label = "xAI"
    default_base_url = "https://api.x.ai/v1"
    # xAI's Responses reference does not document `instructions` (it only appears as null in
    # examples), so the system prompt goes in as a system message, which it does accept.
    system_as_message = True
    # xAI's pricing page lists reasoning tokens as a separately billed token type and does not
    # say whether output_tokens already includes them. Adding them can only over-count, which
    # keeps the spending cap safe; compare with the xAI console after real calls.
    add_reasoning_tokens = True


def _system(content: str) -> EasyInputMessageParam:
    return {"role": "system", "content": content}


def _input(role: str, content: str) -> EasyInputMessageParam:
    if role == "assistant":
        return {"role": "assistant", "content": content}
    return {"role": "user", "content": content}
