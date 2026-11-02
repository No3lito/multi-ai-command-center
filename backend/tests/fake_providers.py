"""FAKE Anthropic and OpenAI HTTP endpoints for tests. Nothing here talks to a real provider.

The app is pointed at this server with ANTHROPIC_BASE_URL / OPENAI_BASE_URL, so the complete
live code path (keys, official SDKs, HTTP, cost accounting, spending cap) runs end to end
without spending money. Every response is fabricated and says so.

Run: python -m tests.fake_providers --port N [--delay SECONDS] [--reply-suffix TEXT]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time

import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

STATE: dict[str, object] = {
    "anthropic": 0,
    "openai": 0,
    "xai": 0,
    "requests": [],
    "delay": 0.0,
    "models": [],
    "suffix": "",
}
FAKE_IN, FAKE_OUT = 100, 50  # fixed token usage per call, so expected cost is exact


async def anthropic_messages(request: Request) -> JSONResponse:
    body = json.loads(await request.body())
    STATE["anthropic"] = int(STATE["anthropic"]) + 1  # type: ignore[call-overload]
    STATE["requests"].append({"provider": "anthropic", "body": body})  # type: ignore[attr-defined]
    STATE["models"].append(body["model"])  # type: ignore[attr-defined]
    await asyncio.sleep(float(STATE["delay"]))  # type: ignore[arg-type]
    return JSONResponse(
        {
            "id": f"msg_fake_{STATE['anthropic']}",
            "type": "message",
            "role": "assistant",
            "model": body["model"],
            "content": [
                {
                    "type": "text",
                    "text": f"[FAKE PROVIDER] Anthropic answer #{STATE['anthropic']}.{STATE['suffix']}",
                }
            ],
            "stop_reason": "end_turn",
            "stop_sequence": None,
            "usage": {
                "input_tokens": FAKE_IN,
                "output_tokens": FAKE_OUT,
                "cache_read_input_tokens": 0,
                "cache_creation_input_tokens": 0,
            },
        }
    )


FAKE_REASONING = 20  # xAI only: reported separately, as in xAI's documented usage examples


async def openai_responses(request: Request) -> JSONResponse:
    return await _responses(request, "openai", "OpenAI")


async def xai_responses(request: Request) -> JSONResponse:
    return await _responses(request, "xai", "xAI")


async def _responses(request: Request, provider: str, label: str) -> JSONResponse:
    body = json.loads(await request.body())
    STATE[provider] = int(STATE[provider]) + 1  # type: ignore[call-overload]
    STATE["models"].append(body["model"])  # type: ignore[attr-defined]
    STATE["requests"].append({"provider": provider, "body": body})  # type: ignore[attr-defined]
    n = STATE[provider]
    reasoning = FAKE_REASONING if provider == "xai" else 0
    await asyncio.sleep(float(STATE["delay"]))  # type: ignore[arg-type]
    return JSONResponse(
        {
            "id": f"resp_fake_{provider}_{n}",
            "object": "response",
            "created_at": int(time.time()),
            "status": "completed",
            "model": body["model"],
            "output": [
                {
                    "type": "message",
                    "id": "m1",
                    "status": "completed",
                    "role": "assistant",
                    "content": [
                        {
                            "type": "output_text",
                            "text": f"[FAKE PROVIDER] {label} answer #{n}.{STATE['suffix']}",
                            "annotations": [],
                        }
                    ],
                }
            ],
            "parallel_tool_calls": False,
            "tool_choice": "auto",
            "tools": [],
            "usage": {
                "input_tokens": FAKE_IN,
                "output_tokens": FAKE_OUT,
                "total_tokens": FAKE_IN + FAKE_OUT,
                "input_tokens_details": {"cached_tokens": 0},
                "output_tokens_details": {"reasoning_tokens": reasoning},
            },
        }
    )


async def calls(_request: Request) -> JSONResponse:
    return JSONResponse(STATE)


async def health(_request: Request) -> JSONResponse:
    return JSONResponse({"ok": True})


app = Starlette(
    routes=[
        Route("/v1/messages", anthropic_messages, methods=["POST"]),
        Route("/v1/responses", openai_responses, methods=["POST"]),
        Route("/xai/v1/responses", xai_responses, methods=["POST"]),
        Route("/calls", calls),
        Route("/health", health),
    ]
)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--delay", type=float, default=0.0)
    parser.add_argument("--reply-suffix", default="", help="appended to every answer, e.g. @mentions")
    args = parser.parse_args()
    STATE["delay"] = args.delay
    STATE["suffix"] = args.reply_suffix
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")
