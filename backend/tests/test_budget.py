"""Spending-cap enforcement, against a real PostgreSQL database.

The provider here is a FAKE adapter (no network). What is being proven is the money logic
in ModelPort: reservation before the call, refusal when the cap would be exceeded, correct
settlement, and safety under concurrency.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from command_center.config import Settings
from command_center.db import models
from command_center.ids import new_id
from command_center.providers.base import ChatMessage, ChatRequest, ChatResponse, ProviderError
from command_center.providers.model_port import BudgetExceeded, ModelPort, ProviderNotReady

SONNET_IN, SONNET_OUT = Decimal(2), Decimal(10)  # $ per 1M tokens (prices.json)


class FakeAdapter:
    """Records calls; checks that money was reserved BEFORE it was called."""

    id = "anthropic"
    simulated = False

    def __init__(
        self,
        port_ref: list[ModelPort],
        sm: async_sessionmaker[AsyncSession],
        *,
        fail: ProviderError | None = None,
        delay: float = 0.0,
    ) -> None:
        self.calls = 0
        self.port_ref = port_ref
        self.sm = sm
        self.fail = fail
        self.delay = delay
        self.reserved_seen: list[Decimal] = []

    def capabilities(self, model: str):  # type: ignore[no-untyped-def]
        return None

    async def generate(self, req: ChatRequest) -> ChatResponse:
        self.calls += 1
        async with self.sm() as s:
            cap = await s.get(models.SpendCap, self.port_ref[0].scope)
            assert cap is not None
            self.reserved_seen.append(cap.reserved_usd)
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.fail:
            raise self.fail
        return ChatResponse(text="ok", input_tokens=1000, output_tokens=500, model=req.model)


@pytest.fixture
async def sm(database_url: str) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(database_url.replace("postgresql://", "postgresql+asyncpg://", 1))
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


async def make_agent(
    sm: async_sessionmaker[AsyncSession],
    provider: str = "anthropic",
    model: str = "claude-sonnet-5-5",
    max_out: int = 1024,
) -> models.AgentProfile:
    async with sm() as s:
        p = models.Principal(id=new_id("agt"), kind="agent", display_name=f"T{uuid.uuid4().hex[:6]}")
        s.add(p)
        await s.flush()
        a = models.AgentProfile(
            principal_id=p.id,
            role="Tester",
            provider=provider,
            model=model,
            system_prompt="",
            max_output_tokens=max_out,
            enabled=True,
        )
        s.add(a)
        await s.commit()
        return a


def settings(database_url: str, cap: float, mode: str = "live", key: str | None = "sk-fake") -> Settings:
    return Settings(
        database_url=database_url,
        owner_password="long-enough-password",  # type: ignore[arg-type]
        anthropic_api_key=key,
        provider_mode=mode,
        live_budget_usd=cap,
    )  # type: ignore[arg-type]


async def port_with(
    sm: async_sessionmaker[AsyncSession], cfg: Settings, **adapter_kwargs: object
) -> tuple[ModelPort, FakeAdapter]:
    ref: list[ModelPort] = []
    adapter = FakeAdapter(ref, sm, **adapter_kwargs)  # type: ignore[arg-type]
    port = ModelPort(
        cfg, sm, adapter_factory=lambda provider, key: adapter, scope=f"test_{uuid.uuid4().hex[:8]}"
    )
    ref.append(port)
    await port.ensure_cap()
    return port, adapter


def req(chars: int = 400, max_out: int = 1024) -> ChatRequest:
    return ChatRequest(
        model="claude-sonnet-5-5",
        system="s",
        messages=[ChatMessage("user", "x" * chars)],
        max_output_tokens=max_out,
    )


async def cap_row(sm: async_sessionmaker[AsyncSession], scope: str) -> models.SpendCap:
    async with sm() as s:
        row = await s.get(models.SpendCap, scope)
        assert row is not None
        return row


async def test_reserves_before_calling_and_settles_actual(sm, database_url: str) -> None:  # type: ignore[no-untyped-def]
    port, adapter = await port_with(sm, settings(database_url, cap=10))
    agent = await make_agent(sm)
    result = await port.call(agent, req(), run_id=None)
    assert adapter.calls == 1
    assert adapter.reserved_seen[0] > 0, "money must be reserved before the provider is called"
    expected = (1000 * SONNET_IN + 500 * SONNET_OUT) / Decimal(1_000_000)
    assert result.cost_usd == expected
    row = await cap_row(sm, port.scope)
    assert row.spent_usd == expected and row.reserved_usd == 0
    async with sm() as s:
        entry = (
            await s.scalars(select(models.UsageEntry).where(models.UsageEntry.agent_id == agent.principal_id))
        ).one()
        assert entry.simulated is False and entry.cost_usd == expected


async def test_cap_blocks_request_before_it_is_sent(sm, database_url: str) -> None:  # type: ignore[no-untyped-def]
    # Worst case for 1024 output tokens at $10/M is about $0.01; a $0.005 cap must refuse.
    port, adapter = await port_with(sm, settings(database_url, cap=0.005))
    agent = await make_agent(sm)
    with pytest.raises(BudgetExceeded):
        await port.call(agent, req(), run_id=None)
    assert adapter.calls == 0, "no request may be sent when the cap would be exceeded"
    row = await cap_row(sm, port.scope)
    assert row.spent_usd == 0 and row.reserved_usd == 0


async def test_run_budget_blocks_too(sm, database_url: str, server) -> None:  # type: ignore[no-untyped-def]
    port, adapter = await port_with(sm, settings(database_url, cap=10))
    agent = await make_agent(sm)
    async with sm() as s:
        owner = await s.scalar(select(models.Principal).where(models.Principal.kind == "owner"))
        room = await s.scalar(select(models.Room).limit(1))
        assert owner is not None and room is not None
        run = models.Run(
            id=new_id("run"),
            room_id=room.id,
            kind="reply",
            status="running",
            step="reply",
            goal="g",
            agent_id=agent.principal_id,
            budget_usd=Decimal("0.001"),
            spent_usd=Decimal(0),
            simulated=False,
            created_by=owner.id,
        )
        s.add(run)
        await s.commit()
    with pytest.raises(BudgetExceeded) as info:
        await port.call(agent, req(), run_id=run.id)
    assert info.value.scope == "run" and adapter.calls == 0


async def test_clear_rejection_releases_reservation(sm, database_url: str) -> None:  # type: ignore[no-untyped-def]
    fail = ProviderError("auth_failed", "bad key", retryable=False, maybe_billed=False)
    port, _adapter = await port_with(sm, settings(database_url, cap=10), fail=fail)
    with pytest.raises(ProviderError):
        await port.call(await make_agent(sm), req(), run_id=None)
    row = await cap_row(sm, port.scope)
    assert row.spent_usd == 0 and row.reserved_usd == 0


async def test_unknown_outcome_counts_full_reservation_as_spent(sm, database_url: str) -> None:  # type: ignore[no-untyped-def]
    fail = ProviderError("unavailable", "timeout", retryable=True, maybe_billed=True)
    port, _adapter = await port_with(sm, settings(database_url, cap=10), fail=fail)
    with pytest.raises(ProviderError):
        await port.call(await make_agent(sm), req(), run_id=None)
    row = await cap_row(sm, port.scope)
    assert row.spent_usd > 0 and row.reserved_usd == 0, "possible charges are never under-counted"


async def test_concurrent_calls_never_exceed_cap(sm, database_url: str) -> None:  # type: ignore[no-untyped-def]
    # Each call reserves about $0.0107 worst case; a $0.05 cap allows at most 4 at once.
    port, adapter = await port_with(sm, settings(database_url, cap=0.05), delay=0.2)
    agent = await make_agent(sm)
    results = await asyncio.gather(
        *[port.call(agent, req(), run_id=None) for _ in range(20)], return_exceptions=True
    )
    ok = [r for r in results if not isinstance(r, BaseException)]
    blocked = [r for r in results if isinstance(r, BudgetExceeded)]
    assert len(ok) + len(blocked) == 20
    assert adapter.calls == len(ok) <= 4
    assert max(adapter.reserved_seen) <= Decimal("0.05")
    row = await cap_row(sm, port.scope)
    assert row.spent_usd + row.reserved_usd <= row.cap_usd


async def test_unknown_price_and_missing_key_are_refused(sm, database_url: str) -> None:  # type: ignore[no-untyped-def]
    port, adapter = await port_with(sm, settings(database_url, cap=10))
    with pytest.raises(ProviderNotReady) as info:
        await port.call(await make_agent(sm, model="claude-imaginary-9"), req(), run_id=None)
    assert info.value.status == "unknown_price"
    port2, adapter2 = await port_with(sm, settings(database_url, cap=10, key=None))
    with pytest.raises(ProviderNotReady) as info2:
        await port2.call(await make_agent(sm), req(), run_id=None)
    assert info2.value.status == "missing_key"
    assert adapter.calls == 0 and adapter2.calls == 0


async def test_simulated_mode_costs_nothing_and_is_labeled(sm, database_url: str) -> None:  # type: ignore[no-untyped-def]
    port, adapter = await port_with(sm, settings(database_url, cap=10, mode="simulated"))
    agent = await make_agent(sm)
    result = await port.call(agent, req(), run_id=None)
    assert result.simulated and result.cost_usd == 0 and adapter.calls == 0
    assert "Simulated response, no AI model was called" in result.response.text
    row = await cap_row(sm, port.scope)
    assert row.spent_usd == 0 and row.reserved_usd == 0
    async with sm() as s:
        entry = (
            await s.scalars(select(models.UsageEntry).where(models.UsageEntry.agent_id == agent.principal_id))
        ).one()
        assert entry.simulated is True and entry.cost_usd == 0


async def test_stale_reservations_settle_as_spent(sm, database_url: str) -> None:  # type: ignore[no-untyped-def]
    port, _ = await port_with(sm, settings(database_url, cap=10))
    async with sm() as s:
        cap = await s.get(models.SpendCap, port.scope)
        assert cap is not None
        cap.reserved_usd = Decimal("0.02")
        s.add(
            models.BudgetReservation(
                id=new_id("res"), scope=port.scope, amount_usd=Decimal("0.02"), status="reserved"
            )
        )
        await s.commit()
        await s.execute(
            models.BudgetReservation.__table__.update()
            .where(models.BudgetReservation.scope == port.scope)
            .values(created_at=models.func.now() - models.func.make_interval(0, 0, 0, 0, 1))
        )
        await s.commit()
    assert await port.settle_stale_reservations() == 1
    row = await cap_row(sm, port.scope)
    assert row.spent_usd == Decimal("0.02") and row.reserved_usd == 0


async def test_cap_never_lowered_below_spend(sm, database_url: str) -> None:  # type: ignore[no-untyped-def]
    port, _ = await port_with(sm, settings(database_url, cap=10))
    await port.call(await make_agent(sm), req(), run_id=None)
    spent = (await cap_row(sm, port.scope)).spent_usd
    lowered = ModelPort(settings(database_url, cap=0), sm, scope=port.scope)
    await lowered.ensure_cap()
    row = await cap_row(sm, port.scope)
    assert row.cap_usd == spent, "a lower setting stops further spending but keeps history consistent"
