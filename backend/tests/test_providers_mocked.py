"""MOCKED provider tests: no real API is called.

These verify that each adapter sends the request shape the official SDK expects and parses
usage correctly, using fabricated HTTP responses. They do NOT prove the live APIs work;
that is what tests/test_live_providers.py (opt-in, real keys, budget-capped) is for.
"""

from __future__ import annotations

import json
from typing import Any

import httpx2
import pytest

from command_center.providers.anthropic_adapter import AnthropicAdapter
from command_center.providers.base import ChatMessage, ChatRequest, ProviderError
from command_center.providers.openai_adapter import OpenAIAdapter
from command_center.providers.prices import estimate_input_tokens, price_for

REQ = ChatRequest(
    model="claude-sonnet-5-5",
    system="You are a test agent.",
    messages=[ChatMessage(role="user", content="Say hello.")],
    max_output_tokens=64,
)


def transport(status: int, body: dict[str, Any] | None, seen: list[httpx2.Request]) -> httpx2.MockTransport:
    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(status, json=body or {})

    return httpx2.MockTransport(handler)


ANTHROPIC_OK = {
    "id": "msg_test",
    "type": "message",
    "role": "assistant",
    "model": "claude-sonnet-5-5",
    "content": [{"type": "text", "text": "Hello from a fabricated response."}],
    "stop_reason": "end_turn",
    "stop_sequence": None,
    "usage": {
        "input_tokens": 21,
        "output_tokens": 7,
        "cache_read_input_tokens": 0,
        "cache_creation_input_tokens": 0,
    },
}

OPENAI_OK = {
    "id": "resp_test",
    "object": "response",
    "created_at": 1_790_000_000,
    "status": "completed",
    "model": "gpt-6.1-sol",
    "output": [
        {
            "type": "message",
            "id": "msg_1",
            "status": "completed",
            "role": "assistant",
            "content": [
                {"type": "output_text", "text": "Hello from a fabricated response.", "annotations": []}
            ],
        }
    ],
    "parallel_tool_calls": False,
    "tool_choice": "auto",
    "tools": [],
    "usage": {
        "input_tokens": 30,
        "output_tokens": 9,
        "total_tokens": 39,
        "input_tokens_details": {"cached_tokens": 0},
        "output_tokens_details": {"reasoning_tokens": 0},
    },
}


async def test_anthropic_request_shape_and_usage() -> None:
    seen: list[httpx2.Request] = []
    adapter = AnthropicAdapter(
        "sk-test", http_client=httpx2.AsyncClient(transport=transport(200, ANTHROPIC_OK, seen))
    )
    resp = await adapter.generate(REQ)
    assert resp.text == "Hello from a fabricated response."
    assert (resp.input_tokens, resp.output_tokens) == (21, 7)
    assert len(seen) == 1, "exactly one request, no automatic retries"
    req = seen[0]
    assert req.url.path == "/v1/messages"
    assert req.headers.get("x-api-key") == "sk-test" or req.headers.get("authorization") == "Bearer sk-test"
    body = json.loads(req.content)
    assert body["model"] == "claude-sonnet-5-5"
    assert body["max_tokens"] == 64
    assert body["system"] == "You are a test agent."
    assert body["messages"] == [{"role": "user", "content": "Say hello."}]


async def test_openai_request_shape_and_usage() -> None:
    seen: list[httpx2.Request] = []
    adapter = OpenAIAdapter(
        "sk-test", http_client=httpx2.AsyncClient(transport=transport(200, OPENAI_OK, seen))
    )
    resp = await adapter.generate(
        ChatRequest(model="gpt-6.1-sol", system=REQ.system, messages=REQ.messages, max_output_tokens=64)
    )
    assert resp.text == "Hello from a fabricated response."
    assert (resp.input_tokens, resp.output_tokens) == (30, 9)
    assert len(seen) == 1
    req = seen[0]
    assert req.url.path == "/v1/responses"
    assert req.headers["authorization"] == "Bearer sk-test"
    body = json.loads(req.content)
    assert body["model"] == "gpt-6.1-sol"
    assert body["instructions"] == "You are a test agent."
    assert body["max_output_tokens"] == 64
    assert body["store"] is False
    assert body["input"] == [{"role": "user", "content": "Say hello."}]


@pytest.mark.parametrize(
    ("status", "code", "billed"),
    [
        (401, "auth_failed", False),
        (429, "rate_limited", False),
        (400, "bad_request", False),
        (500, "unavailable", True),
        (529, "unavailable", True),
    ],
)
async def test_anthropic_error_mapping(status: int, code: str, billed: bool) -> None:
    seen: list[httpx2.Request] = []
    err = {"type": "error", "error": {"type": "x", "message": "fabricated"}}
    adapter = AnthropicAdapter(
        "sk-test", http_client=httpx2.AsyncClient(transport=transport(status, err, seen))
    )
    with pytest.raises(ProviderError) as info:
        await adapter.generate(REQ)
    assert info.value.code == code
    assert info.value.maybe_billed is billed
    assert len(seen) == 1, "never retried automatically"


@pytest.mark.parametrize(
    ("status", "code", "billed"), [(401, "auth_failed", False), (500, "unavailable", True)]
)
async def test_openai_error_mapping(status: int, code: str, billed: bool) -> None:
    seen: list[httpx2.Request] = []
    err = {"error": {"message": "fabricated", "type": "x", "code": "x"}}
    adapter = OpenAIAdapter("sk-test", http_client=httpx2.AsyncClient(transport=transport(status, err, seen)))
    with pytest.raises(ProviderError) as info:
        await adapter.generate(
            ChatRequest(model="gpt-6.1-sol", system="s", messages=REQ.messages, max_output_tokens=16)
        )
    assert info.value.code == code
    assert info.value.maybe_billed is billed
    assert len(seen) == 1


async def test_timeout_counts_as_possibly_billed() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ReadTimeout("fabricated timeout", request=request)

    adapter = AnthropicAdapter(
        "sk-test", http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler))
    )
    with pytest.raises(ProviderError) as info:
        await adapter.generate(REQ)
    assert info.value.code == "unavailable" and info.value.maybe_billed is True


def test_price_table_and_estimates() -> None:
    sonnet = price_for("anthropic", "claude-sonnet-5-5")
    assert sonnet is not None
    # 1M input + 1M output tokens at $2 + $10
    assert str(sonnet.cost(1_000_000, 1_000_000)) == "12.000000"
    haiku = price_for("anthropic", "claude-haiku-5-5")
    assert haiku is not None
    assert haiku.cost(100_000, 0) < haiku.cost(100_001, 0) / 4  # long-context rate kicks in above 100k
    assert price_for("openai", "gpt-6.1-sol") is not None
    assert price_for("openai", "made-up-model") is None
    # Conservative estimate: more tokens than a typical 4 chars/token count.
    assert estimate_input_tokens(4000) > 1000
