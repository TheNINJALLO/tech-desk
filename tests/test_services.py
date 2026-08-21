from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from conftest import complete_report

from kingdom_tech_desk.database.repositories import KnownIssueRepository, TicketRepository
from kingdom_tech_desk.models.core import Severity, TicketRecord, TicketStatus
from kingdom_tech_desk.services.duplicate_detection import DuplicateDetectionService
from kingdom_tech_desk.services.rate_limits import RateLimitService
from kingdom_tech_desk.services.server_context import DisabledServerContextProvider
from kingdom_tech_desk.services.severity import SeverityService
from kingdom_tech_desk.services.transcripts import TranscriptService


def test_severity_critical_for_everyone_access_outage():
    report = complete_report(affected_scope="everyone", category="proxy_transfer")
    assert SeverityService().suggest(report) == Severity.CRITICAL


def test_severity_low_for_visual_issue():
    report = complete_report(category="visual", affected_scope="only_me")
    assert SeverityService().suggest(report) == Severity.LOW


@pytest.mark.asyncio
async def test_disabled_onilink_adapter_never_raises():
    snapshot = await DisabledServerContextProvider().snapshot("kingdom")
    assert not snapshot.available
    assert snapshot.error


@pytest.mark.asyncio
async def test_rate_limit_blocks_after_limit(database):
    service = RateLimitService(database)
    assert (await service.hit(1, 2, "start", 2, 60))[0]
    assert (await service.hit(1, 2, "start", 2, 60))[0]
    assert not (await service.hit(1, 2, "start", 2, 60))[0]


@pytest.mark.asyncio
async def test_duplicate_detector_matches_known_issue(database):
    tickets = TicketRepository(database)
    known = KnownIssueRepository(database)
    await known.add(
        guild_id=1,
        public_title="Kingdom transfer returns connection error",
        category="proxy_transfer",
        created_by=9,
        workaround="Join directly",
        platforms=["xbox"],
    )
    matches = await DuplicateDetectionService(tickets, known).find_matches(1, complete_report(), 30)
    assert matches and matches[0].kind == "known_issue"


def test_transcript_contains_structured_report_and_conversation(tmp_path: Path):
    now = datetime.now(UTC)
    ticket = TicketRecord(
        id=7,
        guild_id=8,
        ticket_number=9,
        public_id="KTS-8-000009",
        draft_id=3,
        reporter_id=10,
        channel_id=11,
        status=TicketStatus.CLOSED,
        severity=Severity.HIGH,
        assignee_id=12,
        data=complete_report(),
        created_at=now,
        updated_at=now,
        closed_at=now,
        closure_reason="Fixed",
        resolution_type="FIXED",
    )
    author = SimpleNamespace(id=10, display_name="Reporter", bot=False)
    message = SimpleNamespace(
        id=100,
        author=author,
        content="The error happened again after the same steps.",
        created_at=now,
        edited_at=None,
        attachments=[],
        embeds=[],
    )
    service = TranscriptService(tmp_path / "transcripts")
    html_path, json_path, structured_path = service.create(
        ticket,
        [message],
        [{"event_type": "CLOSED", "created_at": now.isoformat()}],
    )
    assert "The error happened again" in html_path.read_text(encoding="utf-8")
    archive = json.loads(json_path.read_text(encoding="utf-8"))
    assert archive["messages"][0]["author_name"] == "Reporter"
    structured = json.loads(structured_path.read_text(encoding="utf-8"))
    assert structured["intake"]["gamertag"] == "NinjaPlayer"
