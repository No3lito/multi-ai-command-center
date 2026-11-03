"""Grok (xAI) agent.

FAKE PROVIDER: the live code path (key, official OpenAI SDK pointed at xAI's API shape, HTTP,
cost, cap) against the local fake server. Proves the plumbing, not the real xAI API.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import delete, select

from command_center import routes_b
from command_center.config import Settings
from command_center.db import models
from command_center.db.session import Database
from tests.conftest import run_fake_providers, run_server
from tests.test_coordinator import fake_calls, general_and_agents, logged_in, run_messages, wait_run


async def test_grok_reviews_a_plan_through_the_live_code_path(
    fresh_database_url: str, tmp_path: Path
) -> None:
    with run_fake_providers() as fake:
        env = {
            "ANTHROPIC_API_KEY": "sk-ant-fake",
            "ANTHROPIC_BASE_URL": fake,
            "XAI_API_KEY": "xai-fake",
            "XAI_BASE_URL": f"{fake}/xai/v1",
            "LIVE_BUDGET_USD": "1.00",
        }
        with run_server(fresh_database_url, tmp_path, **env) as srv:
            async with logged_in(srv) as c:
                room_id, agents = await general_and_agents(c)
                grok = agents["Grok"]
                assert (grok["provider"], grok["model"], grok["status"]) == (
                    "xai",
                    "grok-build-0.1",
                    "live",
                )
                assert agents["GPT"]["status"] == "missing_key", "no OpenAI key in this test"
                r = await c.post(
                    f"/api/rooms/{room_id}/runs",
                    json={
                        "goal": "Plan a launch checklist",
                        "planner_id": agents["Claude"]["id"],
                        "critic_id": grok["id"],
                    },
                )
                assert r.status_code == 201, r.text
                done = await wait_run(c, r.json()["id"])
                assert done["status"] == "completed", done
                calls = await fake_calls(fake)
                assert (calls["anthropic"], calls["xai"], calls["openai"]) == (3, 1, 0)
                xai_body = next(q["body"] for q in calls["requests"] if q["provider"] == "xai")
                assert xai_body["input"][0]["role"] == "system" and xai_body["store"] is False
                # Claude: 2 x (100 in, 50 out) at $2/$10 = $0.0014.
                # Grok (grok-build-0.1): 100 in, 50 out + 20 reasoning at $1/$2 per 1M = $0.00024.
                assert done["spent_usd"] == pytest.approx(0.0021 + 0.00024)  # Claude x3 incl. brief
                chats = [m for m in await run_messages(c, room_id, done["id"]) if m["kind"] == "chat"]
                assert [m["sender"]["display_name"] for m in chats] == ["Claude", "Grok", "Claude", "Claude"]
                assert chats[1]["body"]["data"]["provider"] == "xai"
                assert "[FAKE PROVIDER] xAI answer" in chats[1]["body"]["text"]


async def test_existing_install_gets_grok_once(fresh_database_url: str) -> None:
    settings = Settings(
        database_url=fresh_database_url,
        owner_password="long-enough-password",  # type: ignore[arg-type]
    )
    from command_center.app import bootstrap

    db = Database(settings.database_url)
    try:
        await bootstrap(db, settings)
        await routes_b.seed(db, settings)
        async with db.sessionmaker() as s:  # simulate an install from before Grok existed
            grok_id = await s.scalar(
                select(models.AgentProfile.principal_id).where(models.AgentProfile.provider == "xai")
            )
            await s.execute(delete(models.RoomMember).where(models.RoomMember.principal_id == grok_id))
            await s.execute(delete(models.AgentProfile).where(models.AgentProfile.principal_id == grok_id))
            await s.execute(delete(models.Principal).where(models.Principal.id == grok_id))
            await s.commit()
        await routes_b.seed(db, settings)
        await routes_b.seed(db, settings)
        async with db.sessionmaker() as s:
            names = sorted(
                (
                    await s.scalars(
                        select(models.Principal.display_name).where(models.Principal.kind == "agent")
                    )
                ).all()
            )
            general = await s.scalar(select(models.Room).where(models.Room.name == "General"))
            assert general is not None
            members = (
                await s.scalars(
                    select(models.Principal.display_name)
                    .join(models.RoomMember, models.RoomMember.principal_id == models.Principal.id)
                    .where(models.RoomMember.room_id == general.id, models.Principal.kind == "agent")
                )
            ).all()
        assert names == ["Claude", "GPT", "Grok"], "Grok added exactly once; Claude and GPT not duplicated"
        assert sorted(members) == ["Claude", "GPT", "Grok"]
    finally:
        await db.dispose()
