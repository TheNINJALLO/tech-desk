from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from kingdom_tech_desk.database import Database, run_migrations
from kingdom_tech_desk.database.repositories import (
    DraftRepository,
    IncidentRepository,
    KnownIssueRepository,
    TicketRepository,
)
from kingdom_tech_desk.models.core import DraftStage, DraftStatus, ResolutionType, Severity, TicketStatus

from conftest import complete_report


@pytest.mark.asyncio
async def test_draft_survives_database_restart(tmp_path: Path):
    path = tmp_path / "restart.db"
    db = Database(path)
    await db.connect()
    await run_migrations(db)
    repo = DraftRepository(db)
    draft = await repo.create_or_get(1, 2, 24)
    await repo.save_stage(draft.id, DraftStage.CONTEXT, {"gamertag": "PersistMe"}, 24)
    await db.close()

    reopened = Database(path)
    await reopened.connect()
    await run_migrations(reopened)
    loaded = await DraftRepository(reopened).get_active(1, 2)
    assert loaded is not None
    assert loaded.data["gamertag"] == "PersistMe"
    await reopened.close()


@pytest.mark.asyncio
async def test_draft_resumes_at_correct_stage(database):
    repo = DraftRepository(database)
    draft = await repo.create_or_get(10, 20, 24)
    after_context = await repo.save_stage(draft.id, DraftStage.CONTEXT, {"category": "crash"}, 24)
    assert after_context.current_stage == DraftStage.DETAILS
    after_details = await repo.save_stage(
        draft.id,
        DraftStage.DETAILS,
        {"title": "Minecraft closes during transfer"},
        24,
    )
    assert after_details.current_stage == DraftStage.CHECKS


@pytest.mark.asyncio
async def test_expired_draft_is_marked_and_not_resumed(database):
    repo = DraftRepository(database)
    draft = await repo.create_or_get(11, 21, -1)
    expired = await repo.expire_due()
    assert draft.id in expired
    loaded = await repo.get(draft.id)
    assert loaded is not None and loaded.status == DraftStatus.EXPIRED
    assert await repo.get_active(11, 21) is None


@pytest.mark.asyncio
async def test_no_ticket_exists_before_validation_or_creation(database):
    drafts = DraftRepository(database)
    draft = await drafts.create_or_get(12, 22, 24)
    await drafts.patch_data(draft.id, complete_report(), current_stage=DraftStage.COMPLETE)
    row = await database.fetchone("SELECT COUNT(*) AS count FROM tickets")
    assert int(row["count"]) == 0


@pytest.mark.asyncio
async def test_exactly_one_submission_claim_wins_concurrently(database):
    repo = DraftRepository(database)
    draft = await repo.create_or_get(13, 23, 24)
    results = await asyncio.gather(*(repo.claim_for_submission(draft.id) for _ in range(10)))
    assert results.count(True) == 1


@pytest.mark.asyncio
async def test_ticket_numbers_are_atomic_under_concurrency(database):
    repo = TicketRepository(database)
    numbers = await asyncio.gather(*(repo.reserve_number(14) for _ in range(20)))
    assert sorted(numbers) == list(range(1, 21))
    assert len(set(numbers)) == 20


@pytest.mark.asyncio
async def test_ticket_creation_failure_reuses_record(database):
    drafts = DraftRepository(database)
    tickets = TicketRepository(database)
    draft = await drafts.create_or_get(15, 25, 24)
    ticket = await tickets.create_pending(
        guild_id=15,
        number=await tickets.reserve_number(15),
        draft_id=draft.id,
        reporter_id=25,
        severity=Severity.NORMAL,
        data=complete_report(),
    )
    await tickets.mark_creation_failed(ticket.id, "simulated")
    failed = await tickets.get_by_draft(draft.id)
    assert failed is not None and failed.status == TicketStatus.CREATION_FAILED
    await tickets.reset_creation(failed.id)
    retried = await tickets.get(failed.id)
    assert retried is not None and retried.ticket_number == ticket.ticket_number


@pytest.mark.asyncio
async def test_private_ticket_record_can_be_claimed_and_unclaimed(database):
    drafts = DraftRepository(database)
    tickets = TicketRepository(database)
    draft = await drafts.create_or_get(16, 26, 24)
    ticket = await tickets.create_pending(
        guild_id=16,
        number=1,
        draft_id=draft.id,
        reporter_id=26,
        severity=Severity.NORMAL,
        data=complete_report(),
    )
    claimed = await tickets.claim(ticket.id, 500)
    assert claimed.assignee_id == 500 and claimed.status == TicketStatus.CLAIMED
    unclaimed = await tickets.unclaim(ticket.id, 500)
    assert unclaimed.assignee_id is None and unclaimed.status == TicketStatus.OPEN


@pytest.mark.asyncio
async def test_information_request_lifecycle(database):
    drafts = DraftRepository(database)
    tickets = TicketRepository(database)
    draft = await drafts.create_or_get(17, 27, 24)
    ticket = await tickets.create_pending(
        guild_id=17,
        number=1,
        draft_id=draft.id,
        reporter_id=27,
        severity=Severity.NORMAL,
        data=complete_report(),
    )
    request = await tickets.create_information_request(ticket.id, 700, ["steps", "evidence"], "Try again")
    waiting = await tickets.get(ticket.id)
    assert waiting is not None and waiting.status == TicketStatus.WAITING_ON_MEMBER
    await tickets.respond_to_information_request(request.id, 27, "I retried twice and received the same exact message.")
    updated = await tickets.get(ticket.id)
    assert updated is not None and updated.status == TicketStatus.INVESTIGATING


@pytest.mark.asyncio
async def test_transcript_rows_survive_channel_reference_cleanup(database):
    drafts = DraftRepository(database)
    tickets = TicketRepository(database)
    draft = await drafts.create_or_get(18, 28, 24)
    ticket = await tickets.create_pending(
        guild_id=18,
        number=1,
        draft_id=draft.id,
        reporter_id=28,
        severity=Severity.HIGH,
        data=complete_report(),
    )
    await tickets.attach_channel(ticket.id, 999999)
    await tickets.close(
        ticket.id,
        700,
        ResolutionType.FIXED,
        "Fixed in the current deployment.",
        "Reconnect and test again.",
        None,
        72,
    )
    await tickets.add_transcript(ticket.id, "a.html", "a.json", "intake.json", None)
    await tickets.clear_channel_id(ticket.id)
    row = await database.fetchone("SELECT COUNT(*) AS count FROM transcripts WHERE ticket_id = ?", (ticket.id,))
    assert int(row["count"]) == 1
    loaded = await tickets.get(ticket.id)
    assert loaded is not None and loaded.channel_id is None and loaded.closure_reason


@pytest.mark.asyncio
async def test_known_issue_and_incident_storage(database):
    known = KnownIssueRepository(database)
    incidents = IncidentRepository(database)
    tickets = TicketRepository(database)
    drafts = DraftRepository(database)
    issue = await known.add(
        guild_id=19,
        public_title="Hub transfers return connection errors",
        category="proxy_transfer",
        created_by=1,
        workaround="Join The Kingdom directly while the route is repaired.",
    )
    await known.subscribe(int(issue["id"]), 29)
    assert len(await known.list_active(19)) == 1

    draft = await drafts.create_or_get(19, 29, 24)
    ticket = await tickets.create_pending(
        guild_id=19,
        number=1,
        draft_id=draft.id,
        reporter_id=29,
        severity=Severity.HIGH,
        data=complete_report(),
    )
    incident = await incidents.create(
        guild_id=19,
        title="Hub transfer outage",
        category="proxy_transfer",
        created_by=1,
    )
    await incidents.link_ticket(int(incident["id"]), ticket.id, 1)
    assert await incidents.ticket_ids(int(incident["id"])) == [ticket.id]

@pytest.mark.asyncio
async def test_creation_retry_refreshes_severity_and_report_data(database):
    drafts = DraftRepository(database)
    tickets = TicketRepository(database)
    draft = await drafts.create_or_get(20, 30, 24)
    original = complete_report(title="Original technical report title")
    ticket = await tickets.create_pending(
        guild_id=20,
        number=await tickets.reserve_number(20),
        draft_id=draft.id,
        reporter_id=30,
        severity=Severity.NORMAL,
        data=original,
    )
    await tickets.mark_creation_failed(ticket.id, "simulated")

    refreshed_data = complete_report(title="Updated repeatable crash during transfer")
    await tickets.update_creation_data(ticket.id, severity=Severity.HIGH, data=refreshed_data)
    await tickets.reset_creation(ticket.id)

    retried = await tickets.get(ticket.id)
    assert retried is not None
    assert retried.ticket_number == ticket.ticket_number
    assert retried.status == TicketStatus.OPEN
    assert retried.severity == Severity.HIGH
    assert retried.data["title"] == "Updated repeatable crash during transfer"

