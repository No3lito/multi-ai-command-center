"""Fan-out of new-message signals from Postgres LISTEN/NOTIFY to WebSocket subscribers.

A notification only says "room X has new messages". Each subscriber then reads from the
database everything after the last seq it sent, so correctness never depends on a
notification arriving: subscribers also re-check on every heartbeat as a safety net, which
covers a dropped listener connection or a missed notification.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from collections import defaultdict
from typing import Any

import asyncpg  # type: ignore[import-untyped]

from command_center.messaging.service import NOTIFY_CHANNEL

log = logging.getLogger(__name__)


class Subscription:
    def __init__(self, hub: RoomHub, room_id: str) -> None:
        self.hub = hub
        self.room_id = room_id
        self.event = asyncio.Event()

    async def wait(self, max_wait: float) -> bool:
        """True if signalled, False on timeout. Clears the signal."""
        try:
            await asyncio.wait_for(self.event.wait(), max_wait)
        except TimeoutError:
            return False
        self.event.clear()
        return True

    def close(self) -> None:
        self.hub._unsubscribe(self)


class RoomHub:
    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._subs: dict[str, set[Subscription]] = defaultdict(set)
        self._task: asyncio.Task[None] | None = None
        self._stopping = asyncio.Event()
        self.connected = False

    def subscribe(self, room_id: str) -> Subscription:
        sub = Subscription(self, room_id)
        self._subs[room_id].add(sub)
        return sub

    def _unsubscribe(self, sub: Subscription) -> None:
        subs = self._subs.get(sub.room_id)
        if subs is not None:
            subs.discard(sub)
            if not subs:
                del self._subs[sub.room_id]

    def subscriber_count(self) -> int:
        return sum(len(s) for s in self._subs.values())

    def _on_notify(self, _conn: Any, _pid: int, _channel: str, payload: str) -> None:
        try:
            room_id = json.loads(payload)["room_id"]
        except (ValueError, KeyError, TypeError):
            log.warning("ignoring malformed notification payload")
            return
        for sub in list(self._subs.get(room_id, ())):
            sub.event.set()

    def _signal_all(self) -> None:
        for subs in list(self._subs.values()):
            for sub in list(subs):
                sub.event.set()

    async def start(self) -> None:
        self._task = asyncio.create_task(self._run(), name="room-hub-listener")

    async def stop(self) -> None:
        self._stopping.set()
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task

    async def _run(self) -> None:
        backoff = 1.0
        while not self._stopping.is_set():
            conn: asyncpg.Connection | None = None
            try:
                conn = await asyncpg.connect(self._dsn)
                await conn.add_listener(NOTIFY_CHANNEL, self._on_notify)
                self.connected = True
                backoff = 1.0
                log.info("realtime listener connected")
                # Anything committed while we were disconnected: let subscribers re-check.
                self._signal_all()
                while not self._stopping.is_set() and not conn.is_closed():
                    await asyncio.sleep(5)
                    await conn.execute("SELECT 1")
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.warning("realtime listener error, reconnecting: %s", type(exc).__name__)
            finally:
                self.connected = False
                if conn is not None and not conn.is_closed():
                    with contextlib.suppress(Exception):
                        await conn.close()
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30.0)
