"""`command-center live-check`: one tiny REAL request per provider, through the spending cap.

Uses the cheapest models (claude-haiku-5-5, gpt-6-luna, grok-4.20-0309-non-reasoning) with a
16-token output limit, so each
call costs a small fraction of a cent. Every call goes through ModelPort, which reserves the
worst-case cost against LIVE_BUDGET_USD before sending anything.
"""

from __future__ import annotations

import asyncio
import sys
from decimal import Decimal

from sqlalchemy import select

from command_center.config import get_settings
from command_center.db import models
from command_center.db.session import Database
from command_center.providers.base import ChatMessage, ChatRequest, ProviderError
from command_center.providers.model_port import LIVE_SCOPE, BudgetExceeded, ModelPort, ProviderNotReady

CHECKS = (
    ("anthropic", "claude-haiku-5-5", "Claude"),
    ("openai", "gpt-6-luna", "GPT"),
    ("xai", "grok-4.20-0309-non-reasoning", "Grok"),
)


async def run() -> int:
    settings = get_settings()
    if settings.provider_mode != "live":
        print("PROVIDER_MODE is 'simulated'; set it to 'live' in .env to test real providers.")
        return 2
    db = Database(settings.database_url)
    port = ModelPort(settings, db.sessionmaker)
    await port.ensure_cap()
    failures = 0
    checked = 0
    try:
        for provider, model, agent_name in CHECKS:
            if settings.api_key_for(provider) is None:
                print(f"[{provider}] skipped: no {provider.upper()}_API_KEY in .env")
                continue
            checked += 1
            async with db.sessionmaker() as s:
                agent = await s.scalar(
                    select(models.Principal).where(
                        models.Principal.kind == "agent", models.Principal.display_name == agent_name
                    )
                )
            if agent is None:
                print(f"[{provider}] skipped: agent {agent_name} not found (start the app once first)")
                failures += 1
                continue
            # Transient profile: same agent identity, cheapest model, tiny output limit.
            profile = models.AgentProfile(
                principal_id=agent.id,
                role="Live check",
                provider=provider,
                model=model,
                system_prompt="",
                max_output_tokens=16,
                enabled=True,
            )
            req = ChatRequest(
                model=model,
                system="You are a connectivity check.",
                messages=[ChatMessage("user", "Reply with exactly: OK")],
                max_output_tokens=16,
            )
            try:
                result = await port.call(profile, req, run_id=None, simulated=False)
            except (ProviderNotReady, BudgetExceeded) as exc:
                print(f"[{provider}] NOT SENT: {exc}")
                failures += 1
                continue
            except ProviderError as exc:
                print(f"[{provider}] FAILED: {exc.message} ({exc.code})")
                failures += 1
                continue
            r = result.response
            print(
                f"[{provider}] OK  model={r.model}  reply={r.text.strip()[:40]!r}  "
                f"tokens in/out={r.input_tokens}/{r.output_tokens}  cost=${result.cost_usd}"
            )
        async with db.sessionmaker() as s:
            cap = await s.get(models.SpendCap, LIVE_SCOPE)
        if cap is not None:
            remaining = cap.cap_usd - cap.spent_usd - cap.reserved_usd
            spent = cap.spent_usd.quantize(Decimal("0.000001"))
            left = remaining.quantize(Decimal("0.000001"))
            print(
                f"Live spend so far ${spent} of ${cap.cap_usd.quantize(Decimal('0.01'))} cap; ${left} left."
            )
    finally:
        await db.dispose()
    if checked == 0:
        print("No provider keys configured; nothing was checked.")
        return 2
    return 1 if failures else 0


def main() -> None:
    sys.exit(asyncio.run(run()))
