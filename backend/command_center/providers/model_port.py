"""The only way the platform calls a model.

For every PAID call, in this order:
  1. Refuse if the provider has no key or the model has no known price (never guess a price).
  2. Estimate the worst-case cost: conservative input-token estimate plus the full output limit.
  3. Atomically reserve that amount against the instance-wide cap (spend_caps), the run's own
     budget and its run tree's budget (spent plus open reservations). If any would be exceeded,
     the request is NOT sent.
  4. Call the provider, under an overall timeout.
  5. Settle: replace the reservation with the actual cost, recorded truthfully even if it beats
     the estimate. If the outcome is unknown (timeout, dropped connection, server error, missing
     usage report) the full reservation is kept as spent, so spend is never under-counted.
     Clear rejections (bad key, bad request) release it.

Simulated calls skip steps 1 to 3, cost nothing, and are recorded with simulated=true.
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from command_center.config import Settings
from command_center.db import models
from command_center.ids import new_id
from command_center.providers.anthropic_adapter import AnthropicAdapter
from command_center.providers.base import ChatRequest, ChatResponse, ProviderAdapter, ProviderError
from command_center.providers.openai_adapter import OpenAIAdapter, XAIAdapter
from command_center.providers.prices import Price, estimate_input_tokens, price_for
from command_center.providers.simulated import SimulatedAdapter

log = logging.getLogger(__name__)

LIVE_SCOPE = "live_total"
STALE_RESERVATION_AGE = timedelta(minutes=10)


class BudgetExceeded(Exception):
    def __init__(self, scope: str, needed: Decimal, available: Decimal) -> None:
        super().__init__(f"{scope} budget exceeded: needs ${needed} but ${available} is available")
        self.scope = scope
        self.needed = needed
        self.available = available


class ProviderNotReady(Exception):
    def __init__(self, status: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


@dataclass(frozen=True)
class CallResult:
    response: ChatResponse
    cost_usd: Decimal
    simulated: bool
    provider: str
    model: str


AdapterFactory = Callable[[str, str], ProviderAdapter]


def agent_status(settings: Settings, profile: models.AgentProfile) -> str:
    if not profile.enabled:
        return "disabled"
    if settings.provider_mode == "simulated" or profile.provider == "simulated":
        return "simulated"
    if settings.api_key_for(profile.provider) is None:
        return "missing_key"
    if price_for(profile.provider, profile.model) is None:
        return "unknown_price"
    return "live"


class ModelPort:
    def __init__(
        self,
        settings: Settings,
        sessionmaker: async_sessionmaker[AsyncSession],
        adapter_factory: AdapterFactory | None = None,
        scope: str = LIVE_SCOPE,
    ) -> None:
        self.settings = settings
        self.scope = scope
        self.sessionmaker = sessionmaker
        self._factory = adapter_factory or self._default_factory
        self._adapters: dict[str, ProviderAdapter] = {}

    def _default_factory(self, provider: str, api_key: str) -> ProviderAdapter:
        if provider == "anthropic":
            return AnthropicAdapter(api_key, effort=self.settings.anthropic_effort or None)
        if provider == "openai":
            return OpenAIAdapter(api_key)
        if provider == "xai":
            # XAI_BASE_URL exists for tests against a local fake server, like the SDKs' own
            # ANTHROPIC_BASE_URL / OPENAI_BASE_URL; the app warns at startup when any is set.
            return XAIAdapter(api_key, base_url=os.environ.get("XAI_BASE_URL") or None)
        raise ProviderNotReady("unknown_provider", f"Unknown provider {provider}")

    def _adapter(self, provider: str) -> ProviderAdapter:
        if provider not in self._adapters:
            key = self.settings.api_key_for(provider)
            if key is None:
                raise ProviderNotReady("missing_key", f"No API key configured for {provider}")
            self._adapters[provider] = self._factory(provider, key)
        return self._adapters[provider]

    # ------------------------------------------------------------ budget

    async def ensure_cap(self) -> None:
        """Create or update the live cap from settings. Never lowered below what is already used."""
        cap = Decimal(str(self.settings.live_budget_usd))
        async with self.sessionmaker() as s:
            await s.execute(
                text(
                    "INSERT INTO spend_caps (scope, cap_usd, spent_usd, reserved_usd) "
                    "VALUES (:scope, :cap, 0, 0) "
                    "ON CONFLICT (scope) DO UPDATE SET cap_usd = GREATEST(:cap, "
                    "spend_caps.spent_usd + spend_caps.reserved_usd), updated_at = now()"
                ),
                {"scope": self.scope, "cap": cap},
            )
            await s.commit()

    async def settle_stale_reservations(self) -> int:
        """After a crash, open reservations are counted as fully spent (conservative)."""
        cutoff = datetime.now(UTC) - STALE_RESERVATION_AGE
        async with self.sessionmaker() as s:
            stale = (
                await s.scalars(
                    select(models.BudgetReservation)
                    .where(
                        models.BudgetReservation.status == "reserved",
                        models.BudgetReservation.scope == self.scope,
                        models.BudgetReservation.created_at < cutoff,
                    )
                    .with_for_update(skip_locked=True)
                )
            ).all()
            for r in stale:
                await self._settle_locked(s, r, r.amount_usd)
            await s.commit()
            return len(stale)

    async def _open_reserved(self, s: AsyncSession, run_ids: object) -> Decimal:
        total = await s.scalar(
            select(func.coalesce(func.sum(models.BudgetReservation.amount_usd), 0)).where(
                models.BudgetReservation.status == "reserved",
                models.BudgetReservation.run_id.in_(run_ids),  # type: ignore[arg-type]
            )
        )
        return Decimal(total or 0)

    async def _check_run_budgets(self, s: AsyncSession, run_id: str, amount: Decimal) -> None:
        """Run budget and tree budget, counting open reservations. Locks the tree's root row, so
        concurrent calls in one tree are checked one at a time."""
        run = await s.get(models.Run, run_id)
        if run is None:
            return
        root_id = run.root_run_id or run.id
        root = await s.scalar(select(models.Run).where(models.Run.id == root_id).with_for_update())
        await s.refresh(run)
        own = run.spent_usd + await self._open_reserved(s, [run.id])
        if own + amount > run.budget_usd:
            raise BudgetExceeded("run", amount, max(run.budget_usd - own, Decimal(0)))
        if root is None:
            return
        in_tree = (models.Run.root_run_id == root.id) | (models.Run.id == root.id)
        tree_ids = select(models.Run.id).where(in_tree)
        tree_spent = Decimal(
            await s.scalar(select(func.coalesce(func.sum(models.Run.spent_usd), 0)).where(in_tree)) or 0
        )
        used = tree_spent + await self._open_reserved(s, tree_ids)
        if used + amount > root.budget_usd:
            raise BudgetExceeded("run tree", amount, max(root.budget_usd - used, Decimal(0)))

    async def _reserve(self, run_id: str | None, amount: Decimal) -> str:
        async with self.sessionmaker() as s:
            if run_id is not None:
                await self._check_run_budgets(s, run_id, amount)
            row = (
                await s.execute(
                    update(models.SpendCap)
                    .where(
                        models.SpendCap.scope == self.scope,
                        models.SpendCap.spent_usd + models.SpendCap.reserved_usd + amount
                        <= models.SpendCap.cap_usd,
                    )
                    .values(reserved_usd=models.SpendCap.reserved_usd + amount)
                    .returning(models.SpendCap.scope)
                )
            ).first()
            if row is None:
                cap = await s.get(models.SpendCap, self.scope)
                available = (cap.cap_usd - cap.spent_usd - cap.reserved_usd) if cap else Decimal(0)
                await s.rollback()
                raise BudgetExceeded("live spending cap", amount, max(available, Decimal(0)))
            reservation = models.BudgetReservation(
                id=new_id("res"), run_id=run_id, scope=self.scope, amount_usd=amount, status="reserved"
            )
            s.add(reservation)
            await s.commit()
            return reservation.id

    async def _settle_locked(self, s: AsyncSession, r: models.BudgetReservation, actual: Decimal) -> None:
        # Lock order everywhere: run-tree root, then spend cap, then the run itself. _reserve
        # takes the root then the cap; taking them in another order here deadlocked when two
        # runs of one tree reserved and settled at the same moment.
        if r.run_id is not None:
            root_id = await s.scalar(
                select(func.coalesce(models.Run.root_run_id, models.Run.id)).where(models.Run.id == r.run_id)
            )
            if root_id is not None:
                await s.execute(select(models.Run.id).where(models.Run.id == root_id).with_for_update())
        cap = await s.scalar(
            select(models.SpendCap).where(models.SpendCap.scope == r.scope).with_for_update()
        )
        if cap is not None:
            cap.reserved_usd = max(cap.reserved_usd - r.amount_usd, Decimal(0))
            # Always the true amount, even if it beats the estimate (and so the cap). Spend is
            # never hidden; new reservations are refused once spent + reserved reaches the cap.
            if actual > r.amount_usd:
                log.warning(
                    "actual cost %s exceeded the reserved worst case %s (reservation %s)",
                    actual,
                    r.amount_usd,
                    r.id,
                )
            cap.spent_usd = cap.spent_usd + actual
        r.actual_usd = actual
        r.status = "settled" if actual > 0 else "released"
        r.settled_at = datetime.now(UTC)
        if r.run_id is not None and actual > 0:
            await s.execute(
                update(models.Run)
                .where(models.Run.id == r.run_id)
                .values(spent_usd=models.Run.spent_usd + actual)
            )

    async def _settle(self, reservation_id: str, actual: Decimal) -> None:
        async with self.sessionmaker() as s:
            r = await s.scalar(
                select(models.BudgetReservation)
                .where(models.BudgetReservation.id == reservation_id)
                .with_for_update()
            )
            if r is None or r.status != "reserved":
                return
            await self._settle_locked(s, r, actual)
            await s.commit()

    # ------------------------------------------------------------ calls

    async def call(
        self,
        profile: models.AgentProfile,
        req: ChatRequest,
        *,
        run_id: str | None,
        simulated: bool | None = None,
    ) -> CallResult:
        """simulated: the run's own mode, fixed when the run was created (None: use settings)."""
        use_sim = (
            simulated if simulated is not None else self.settings.provider_mode == "simulated"
        ) or profile.provider == "simulated"
        if use_sim:
            if not profile.enabled:
                raise ProviderNotReady("disabled", "This agent is disabled")
            resp = await SimulatedAdapter(profile.role).generate(req)
            await self._record(profile, run_id, resp, Decimal(0), simulated=True, reservation_id=None)
            return CallResult(resp, Decimal(0), True, "simulated", profile.model)
        if self.settings.provider_mode == "simulated":
            raise ProviderNotReady(
                "simulated_mode",
                "This run was created for live providers, but the server is now in simulated mode.",
            )
        status = agent_status(self.settings, profile)
        if status == "disabled":
            raise ProviderNotReady(status, "This agent is disabled")
        if status == "missing_key":
            raise ProviderNotReady(
                status, f"No API key configured for {profile.provider}. Add it to .env and restart."
            )
        price: Price | None = price_for(profile.provider, profile.model)
        if price is None:
            raise ProviderNotReady(
                "unknown_price",
                f"No known price for {profile.provider}:{profile.model}; live calls to it are blocked.",
            )
        adapter = self._adapter(profile.provider)
        worst = price.cost(estimate_input_tokens(req.prompt_bytes()), req.max_output_tokens)
        reservation_id = await self._reserve(run_id, worst)
        timeout = self.settings.provider_call_timeout_seconds
        try:
            try:
                resp = await asyncio.wait_for(adapter.generate(req), timeout)
            except TimeoutError as exc:
                raise ProviderError(
                    "timeout",
                    f"No answer within {timeout:.0f} seconds; counted as billed to be safe",
                    retryable=False,
                    maybe_billed=True,
                ) from exc
        except ProviderError as exc:
            await self._settle(reservation_id, worst if exc.maybe_billed else Decimal(0))
            raise
        except BaseException:
            await self._settle(reservation_id, worst)  # unknown outcome: assume billed
            raise
        if resp.usage_reported:
            actual = price.cost(resp.input_tokens, resp.output_tokens)
        else:
            log.warning("%s did not report usage; counting the full reservation", profile.provider)
            actual = worst
        await self._settle(reservation_id, actual)
        await self._record(profile, run_id, resp, actual, simulated=False, reservation_id=reservation_id)
        log.info(
            "model call %s:%s in=%d out=%d cost=%s",
            profile.provider,
            profile.model,
            resp.input_tokens,
            resp.output_tokens,
            actual,
        )
        return CallResult(resp, actual, False, profile.provider, profile.model)

    async def _record(
        self,
        profile: models.AgentProfile,
        run_id: str | None,
        resp: ChatResponse,
        cost: Decimal,
        *,
        simulated: bool,
        reservation_id: str | None,
    ) -> None:
        async with self.sessionmaker() as s:
            s.add(
                models.UsageEntry(
                    run_id=run_id,
                    agent_id=profile.principal_id,
                    provider="simulated" if simulated else profile.provider,
                    model=profile.model,
                    input_tokens=resp.input_tokens,
                    output_tokens=resp.output_tokens,
                    cost_usd=cost,
                    simulated=simulated,
                    reservation_id=reservation_id,
                )
            )
            await s.commit()
