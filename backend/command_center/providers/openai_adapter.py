"""OpenAI adapter (official `openai` SDK, Responses API)."""

from __future__ import annotations

import httpx2
import openai
from openai.types.responses import EasyInputMessageParam

from command_center.providers.base import Capabilities, ChatRequest, ChatResponse, ErrorCode, ProviderError


class OpenAIAdapter:
    id = "openai"
    simulated = False

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
            api_key=api_key, http_client=http_client, timeout=timeout, max_retries=0, base_url=base_url
        )

    def capabilities(self, model: str) -> Capabilities:
        return Capabilities(streaming=True, tool_calling=True, structured_output=True)

    async def generate(self, req: ChatRequest) -> ChatResponse:
        try:
            resp = await self._client.responses.create(
                model=req.model,
                instructions=req.system,
                input=[_input(m.role, m.content) for m in req.messages],
                max_output_tokens=req.max_output_tokens,
                store=False,  # do not keep conversation state on OpenAI's side
            )
        except openai.AuthenticationError as exc:
            raise ProviderError(
                "auth_failed", "OpenAI rejected the API key", retryable=False, maybe_billed=False
            ) from exc
        except openai.PermissionDeniedError as exc:
            raise ProviderError(
                "auth_failed",
                "OpenAI API key lacks permission for this model",
                retryable=False,
                maybe_billed=False,
            ) from exc
        except openai.RateLimitError as exc:
            raise ProviderError(
                "rate_limited", "OpenAI rate limit or quota reached", retryable=True, maybe_billed=False
            ) from exc
        except openai.BadRequestError as exc:
            text = str(exc).lower()
            code: ErrorCode = "context_overflow" if "context" in text or "too long" in text else "bad_request"
            raise ProviderError(
                code, f"OpenAI rejected the request: {str(exc)[:200]}", retryable=False, maybe_billed=False
            ) from exc
        except openai.NotFoundError as exc:
            raise ProviderError(
                "bad_request", f"Unknown OpenAI model: {req.model}", retryable=False, maybe_billed=False
            ) from exc
        except (openai.APITimeoutError, openai.APIConnectionError) as exc:
            raise ProviderError(
                "unavailable", "OpenAI did not respond in time", retryable=True, maybe_billed=True
            ) from exc
        except openai.APIStatusError as exc:
            raise ProviderError(
                "unavailable",
                f"OpenAI error {exc.status_code}",
                retryable=True,
                maybe_billed=exc.status_code >= 500,
            ) from exc

        usage = resp.usage
        text = resp.output_text or ""
        if resp.status == "incomplete" and not text:
            reason = getattr(resp.incomplete_details, "reason", None) or "unknown"
            failure: ErrorCode = "content_refused" if reason == "content_filter" else "bad_request"
            raise ProviderError(
                failure, f"OpenAI returned no text ({reason})", retryable=False, maybe_billed=True
            )
        return ChatResponse(
            text=text,
            input_tokens=usage.input_tokens if usage else 0,
            output_tokens=usage.output_tokens if usage else 0,
            usage_reported=usage is not None,
            model=resp.model,
            request_id=resp.id,
            stop_reason=resp.status,
        )


def _input(role: str, content: str) -> EasyInputMessageParam:
    if role == "assistant":
        return {"role": "assistant", "content": content}
    return {"role": "user", "content": content}
