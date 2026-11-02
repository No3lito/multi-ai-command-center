"""Durable run worker: claims runs from Postgres with a lease, one step at a time.

A run's state lives in the database, so a restart picks up where it left off. The lease
(FOR UPDATE SKIP LOCKED plus lease_expires_at) guarantees one worker per run at a time;
oldest-updated runs go first, so one long run cannot starve the others.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from command_center.orchestrator.engine import OrchestrationEngine

log = logging.getLogger(__name__)

# Lease of 5 minutes: longer than the provider timeout (90 s).
CLAIM_SQL = text(
    """
    UPDATE runs SET status = 'running', lease_expires_at = now() + interval '5 minutes'
    WHERE id = (
        SELECT id FROM runs
        WHERE status IN ('queued', 'running')
          AND (lease_expires_at IS NULL OR lease_expires_at < now())
        ORDER BY updated_at
        LIMIT 1
        FOR UPDATE SKIP LOCKED
    )
    RETURNING id
    """
)
RELEASE_SQL = text("UPDATE runs SET lease_expires_at = NULL, updated_at = now() WHERE id = :id")
CRASH_SQL = text(
    "UPDATE runs SET status = 'failed', error = 'Internal error while running this step. See server logs.', "
    "lease_expires_at = NULL, finished_at = now(), updated_at = now() "
    "WHERE id = :id AND status IN ('queued', 'running')"
)


class RunWorker:
    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        engine: OrchestrationEngine,
        concurrency: int,
        poll_seconds: float = 1.0,
    ) -> None:
        self.sessionmaker = sessionmaker
        self.engine = engine
        self.concurrency = concurrency
        self.poll_seconds = poll_seconds
        self._wake = asyncio.Event()
        self._tasks: list[asyncio.Task[None]] = []

    def wake(self) -> None:
        self._wake.set()

    async def start(self) -> None:
        self._tasks = [
            asyncio.create_task(self._loop(i), name=f"run-worker-{i}") for i in range(self.concurrency)
        ]

    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await task

    async def _claim(self) -> str | None:
        async with self.sessionmaker() as s:
            run_id: str | None = await s.scalar(CLAIM_SQL)
            await s.commit()
            return run_id

    async def _release(self, run_id: str) -> None:
        async with self.sessionmaker() as s:
            await s.execute(RELEASE_SQL, {"id": run_id})
            await s.commit()

    async def _mark_crashed(self, run_id: str) -> None:
        with contextlib.suppress(Exception):
            async with self.sessionmaker() as s:
                await s.execute(CRASH_SQL, {"id": run_id})
                await s.commit()

    async def _loop(self, index: int) -> None:
        backoff = self.poll_seconds
        while True:
            try:
                run_id = await self._claim()
                backoff = self.poll_seconds
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                # Database unavailable: one short line, exponential backoff, no traceback flood.
                log.warning("run claim failed (%s); retrying in %.0fs", type(exc).__name__, backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30.0)
                continue
            if run_id is None:
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(self._wake.wait(), self.poll_seconds)
                self._wake.clear()
                continue
            try:
                more = await self.engine.step(run_id)
            except asyncio.CancelledError:
                raise
            except Exception:
                # Fail loudly rather than retry forever: a deterministic bug would loop.
                log.exception("run step crashed; marking the run failed")
                await self._mark_crashed(run_id)
                continue
            await self._release(run_id)
            if more:
                self.wake()
