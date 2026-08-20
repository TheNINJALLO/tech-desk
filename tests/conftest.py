from __future__ import annotations

from pathlib import Path

import pytest_asyncio

from kingdom_tech_desk.database import Database, run_migrations


@pytest_asyncio.fixture
async def database(tmp_path: Path):
    db = Database(tmp_path / "kingdom-tech-desk-test.db")
    await db.connect()
    await run_migrations(db)
    try:
        yield db
    finally:
        await db.close()


def complete_report(**overrides):
    report = {
        "category": "proxy_transfer",
        "platform": "xbox",
        "affected_scope": "only_me",
        "gamertag": "NinjaPlayer",
        "where_when": "The Hub transfer NPC near spawn at approximately 8:15 PM Eastern on August 19.",
        "title": "Kingdom transfer returns connection error",
        "steps": (
            "1. I joined The Hub from the multiplayer server list and waited until the world loaded.\n"
            "2. I interacted with the transfer NPC beside the spawn portal.\n"
            "3. I selected The Kingdom from the destination menu and confirmed the transfer.\n"
            "4. I waited through the loading screen until Minecraft returned me to the server list."
        ),
        "expected": "The transfer should have connected me to The Kingdom without leaving the game.",
        "actual": (
            "After about five seconds, Minecraft returned to the server list and displayed "
            "Unable to connect to world. The Hub remained joinable."
        ),
        "category_detail": (
            "The source was The Hub, the destination was The Kingdom, and the failure happened "
            "after the loading screen appeared but before the destination world loaded."
        ),
        "frequency": "every_time",
        "troubleshooting": ["rejoined_server", "restarted_minecraft", "another_player_tested"],
        "client_version": "1.26.44",
        "additional_details": (
            "I restarted Minecraft, repeated the transfer three times, and asked another player to test. "
            "The other player transferred successfully during the same period."
        ),
    }
    report.update(overrides)
    return report
