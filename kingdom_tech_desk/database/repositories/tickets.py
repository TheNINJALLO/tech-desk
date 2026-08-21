from __future__ import annotations

from datetime import timedelta
from typing import Any

from kingdom_tech_desk.database.connection import Database
from kingdom_tech_desk.database.repositories.common import dump_json, iso, load_json, parse_dt, utcnow
from kingdom_tech_desk.models.core import (
    InformationRequest,
    ResolutionType,
    Severity,
    TicketRecord,
    TicketStatus,
)

OPEN_STATUSES = {
    TicketStatus.OPEN,
    TicketStatus.CLAIMED,
    TicketStatus.INVESTIGATING,
    TicketStatus.WAITING_ON_MEMBER,
    TicketStatus.FIX_PENDING,
    TicketStatus.KNOWN_ISSUE,
}


class TicketRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def _row_to_ticket(self, row: Any) -> TicketRecord:
        return TicketRecord(
            id=int(row["id"]),
            guild_id=int(row["guild_id"]),
            ticket_number=int(row["ticket_number"]),
            public_id=str(row["public_id"]),
            draft_id=row["draft_id"],
            reporter_id=int(row["reporter_id"]),
            channel_id=row["channel_id"],
            status=TicketStatus(str(row["status"])),
            severity=Severity(str(row["severity"])),
            assignee_id=row["assignee_id"],
            data=load_json(row["data_json"], {}),
            created_at=parse_dt(row["created_at"]) or utcnow(),
            updated_at=parse_dt(row["updated_at"]) or utcnow(),
            closed_at=parse_dt(row["closed_at"]),
            closure_reason=row["closure_reason"],
            resolution_type=row["resolution_type"],
            user_resolution=row["user_resolution"],
            internal_note=row["internal_note"],
            delete_after=parse_dt(row["delete_after"]),
        )

    async def get(self, ticket_id: int) -> TicketRecord | None:
        row = await self.database.fetchone("SELECT * FROM tickets WHERE id = ?", (ticket_id,))
        return self._row_to_ticket(row) if row else None

    async def get_by_number(self, guild_id: int, ticket_number: int) -> TicketRecord | None:
        row = await self.database.fetchone(
            "SELECT * FROM tickets WHERE guild_id = ? AND ticket_number = ?",
            (guild_id, ticket_number),
        )
        return self._row_to_ticket(row) if row else None

    async def get_by_public_id(self, public_identifier: str) -> TicketRecord | None:
        row = await self.database.fetchone(
            "SELECT * FROM tickets WHERE public_id = ?",
            (public_identifier,),
        )
        return self._row_to_ticket(row) if row else None

    async def get_by_channel(self, channel_id: int) -> TicketRecord | None:
        row = await self.database.fetchone("SELECT * FROM tickets WHERE channel_id = ?", (channel_id,))
        return self._row_to_ticket(row) if row else None

    async def get_by_draft(self, draft_id: int) -> TicketRecord | None:
        row = await self.database.fetchone("SELECT * FROM tickets WHERE draft_id = ?", (draft_id,))
        return self._row_to_ticket(row) if row else None

    async def reserve_number(self, guild_id: int) -> int:
        async with self.database.transaction():
            row = await self.database.fetchone(
                "SELECT next_number FROM ticket_counters WHERE guild_id = ?",
                (guild_id,),
            )
            if row is None:
                number = 1
                await self.database.execute(
                    "INSERT INTO ticket_counters(guild_id, next_number, updated_at) VALUES (?, 2, ?)",
                    (guild_id, iso()),
                )
            else:
                number = int(row["next_number"])
                await self.database.execute(
                    "UPDATE ticket_counters SET next_number = ?, updated_at = ? WHERE guild_id = ?",
                    (number + 1, iso(), guild_id),
                )
            return number

    async def create_pending(
        self,
        *,
        guild_id: int,
        number: int,
        draft_id: int,
        reporter_id: int,
        severity: Severity,
        data: dict[str, Any],
    ) -> TicketRecord:
        now = utcnow()
        public = f"KTS-{guild_id}-{number:06d}"
        cursor = await self.database.execute(
            """
            INSERT INTO tickets(
                guild_id, ticket_number, public_id, draft_id, reporter_id, channel_id,
                status, severity, data_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, NULL, ?, ?, ?, ?, ?)
            """,
            (
                guild_id,
                number,
                public,
                draft_id,
                reporter_id,
                TicketStatus.OPEN,
                severity,
                dump_json(data),
                iso(now),
                iso(now),
            ),
        )
        ticket = await self.get(int(cursor.lastrowid))
        if ticket is None:
            raise RuntimeError("Ticket insert succeeded but could not be read")
        await self.add_event(ticket.id, "TICKET_RESERVED", reporter_id, {"number": number})
        return ticket

    async def attach_channel(self, ticket_id: int, channel_id: int) -> None:
        await self.database.execute(
            "UPDATE tickets SET channel_id = ?, updated_at = ? WHERE id = ?",
            (channel_id, iso(), ticket_id),
        )
        await self.add_event(ticket_id, "CHANNEL_CREATED", None, {"channel_id": channel_id})

    async def reset_creation(self, ticket_id: int) -> None:
        await self.database.execute(
            "UPDATE tickets SET status = ?, updated_at = ? WHERE id = ? AND status = ?",
            (TicketStatus.OPEN, iso(), ticket_id, TicketStatus.CREATION_FAILED),
        )
        await self.add_event(ticket_id, "CREATION_RETRY", None, {})

    async def update_creation_data(
        self,
        ticket_id: int,
        *,
        severity: Severity,
        data: dict[str, Any],
    ) -> None:
        await self.database.execute(
            "UPDATE tickets SET severity = ?, data_json = ?, updated_at = ? WHERE id = ?",
            (severity, dump_json(data), iso(), ticket_id),
        )

    async def mark_creation_failed(self, ticket_id: int, error: str) -> None:
        await self.database.execute(
            "UPDATE tickets SET status = ?, updated_at = ? WHERE id = ?",
            (TicketStatus.CREATION_FAILED, iso(), ticket_id),
        )
        await self.add_event(ticket_id, "CREATION_FAILED", None, {"error": error[:500]})

    async def count_open_for_member(self, guild_id: int, reporter_id: int) -> int:
        placeholders = ",".join("?" for _ in OPEN_STATUSES)
        row = await self.database.fetchone(
            f"SELECT COUNT(*) AS count FROM tickets WHERE guild_id = ? AND reporter_id = ? AND status IN ({placeholders})",
            (guild_id, reporter_id, *[str(status) for status in OPEN_STATUSES]),
        )
        return int(row["count"]) if row else 0

    async def list_recent(self, guild_id: int, minutes: int, limit: int = 100) -> list[TicketRecord]:
        cutoff = utcnow() - timedelta(minutes=minutes)
        rows = await self.database.fetchall(
            """
            SELECT * FROM tickets WHERE guild_id = ? AND created_at >= ?
            ORDER BY created_at DESC LIMIT ?
            """,
            (guild_id, iso(cutoff), limit),
        )
        return [self._row_to_ticket(row) for row in rows]

    async def list_open(self, guild_id: int, limit: int = 200) -> list[TicketRecord]:
        placeholders = ",".join("?" for _ in OPEN_STATUSES)
        rows = await self.database.fetchall(
            f"SELECT * FROM tickets WHERE guild_id = ? AND status IN ({placeholders}) ORDER BY created_at DESC LIMIT ?",
            (guild_id, *[str(status) for status in OPEN_STATUSES], limit),
        )
        return [self._row_to_ticket(row) for row in rows]

    async def list_waiting(self) -> list[TicketRecord]:
        rows = await self.database.fetchall(
            "SELECT * FROM tickets WHERE status = 'WAITING_ON_MEMBER' AND channel_id IS NOT NULL ORDER BY updated_at",
        )
        return [self._row_to_ticket(row) for row in rows]

    async def has_event(self, ticket_id: int, event_type: str) -> bool:
        row = await self.database.fetchone(
            "SELECT 1 FROM ticket_events WHERE ticket_id = ? AND event_type = ? LIMIT 1",
            (ticket_id, event_type),
        )
        return row is not None

    async def list_participant_ids(self, ticket_id: int) -> list[int]:
        rows = await self.database.fetchall(
            "SELECT user_id FROM ticket_participants WHERE ticket_id = ? ORDER BY created_at",
            (ticket_id,),
        )
        return [int(row["user_id"]) for row in rows]

    async def stats(self, guild_id: int) -> dict[str, Any]:
        status_rows = await self.database.fetchall(
            "SELECT status, COUNT(*) AS count FROM tickets WHERE guild_id = ? GROUP BY status",
            (guild_id,),
        )
        severity_rows = await self.database.fetchall(
            "SELECT severity, COUNT(*) AS count FROM tickets WHERE guild_id = ? GROUP BY severity",
            (guild_id,),
        )
        draft_row = await self.database.fetchone(
            "SELECT COUNT(*) AS count FROM drafts WHERE guild_id = ? AND status IN ('ACTIVE', 'SUBMITTING')",
            (guild_id,),
        )
        return {
            "by_status": {str(row["status"]): int(row["count"]) for row in status_rows},
            "by_severity": {str(row["severity"]): int(row["count"]) for row in severity_rows},
            "active_drafts": int(draft_row["count"]) if draft_row else 0,
        }

    async def anonymize_user(self, guild_id: int, user_id: int) -> dict[str, int]:
        async with self.database.transaction():
            drafts = await self.database.fetchone(
                "SELECT COUNT(*) AS count FROM drafts WHERE guild_id = ? AND user_id = ?",
                (guild_id, user_id),
            )
            await self.database.execute(
                "DELETE FROM drafts WHERE guild_id = ? AND user_id = ? AND status != 'SUBMITTED'",
                (guild_id, user_id),
            )
            tickets = await self.database.fetchone(
                "SELECT COUNT(*) AS count FROM tickets WHERE guild_id = ? AND reporter_id = ? AND status = 'CLOSED'",
                (guild_id, user_id),
            )
            await self.database.execute(
                "UPDATE tickets SET reporter_id = 0, data_json = json_set(data_json, '$.gamertag', '[deleted]', '$.discord_user_deleted', 1), updated_at = ? WHERE guild_id = ? AND reporter_id = ? AND status = 'CLOSED'",
                (iso(), guild_id, user_id),
            )
            await self.database.execute(
                "DELETE FROM known_issue_subscribers WHERE user_id = ?",
                (user_id,),
            )
        return {
            "drafts": int(drafts["count"]) if drafts else 0,
            "closed_tickets": int(tickets["count"]) if tickets else 0,
        }

    async def list_without_channels(self) -> list[TicketRecord]:
        rows = await self.database.fetchall(
            "SELECT * FROM tickets WHERE channel_id IS NULL AND status != 'CLOSED'",
        )
        return [self._row_to_ticket(row) for row in rows]

    async def list_channel_ids(self, guild_id: int) -> set[int]:
        rows = await self.database.fetchall(
            "SELECT channel_id FROM tickets WHERE guild_id = ? AND channel_id IS NOT NULL",
            (guild_id,),
        )
        return {int(row["channel_id"]) for row in rows}

    async def add_event(
        self,
        ticket_id: int,
        event_type: str,
        actor_id: int | None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        await self.database.execute(
            "INSERT INTO ticket_events(ticket_id, event_type, actor_id, payload_json, created_at) VALUES (?, ?, ?, ?, ?)",
            (ticket_id, event_type, actor_id, dump_json(payload or {}), iso()),
        )

    async def list_events(self, ticket_id: int) -> list[dict[str, Any]]:
        rows = await self.database.fetchall(
            "SELECT * FROM ticket_events WHERE ticket_id = ? ORDER BY id",
            (ticket_id,),
        )
        return [
            {
                "id": int(row["id"]),
                "event_type": str(row["event_type"]),
                "actor_id": row["actor_id"],
                "payload": load_json(row["payload_json"], {}),
                "created_at": str(row["created_at"]),
            }
            for row in rows
        ]

    async def set_status(self, ticket_id: int, status: TicketStatus, actor_id: int | None) -> TicketRecord:
        previous = await self.get(ticket_id)
        if previous is None:
            raise LookupError("Ticket not found")
        await self.database.execute(
            "UPDATE tickets SET status = ?, updated_at = ? WHERE id = ?",
            (status, iso(), ticket_id),
        )
        await self.add_event(
            ticket_id,
            "STATUS_CHANGED",
            actor_id,
            {"from": previous.status, "to": status},
        )
        updated = await self.get(ticket_id)
        if updated is None:
            raise RuntimeError("Ticket vanished after status update")
        return updated

    async def set_severity(self, ticket_id: int, severity: Severity, actor_id: int) -> TicketRecord:
        previous = await self.get(ticket_id)
        if previous is None:
            raise LookupError("Ticket not found")
        await self.database.execute(
            "UPDATE tickets SET severity = ?, updated_at = ? WHERE id = ?",
            (severity, iso(), ticket_id),
        )
        await self.add_event(
            ticket_id,
            "SEVERITY_CHANGED",
            actor_id,
            {"from": previous.severity, "to": severity},
        )
        updated = await self.get(ticket_id)
        if updated is None:
            raise RuntimeError("Ticket vanished after severity update")
        return updated

    async def claim(self, ticket_id: int, staff_id: int) -> TicketRecord:
        async with self.database.transaction():
            row = await self.database.fetchone("SELECT assignee_id FROM tickets WHERE id = ?", (ticket_id,))
            if row is None:
                raise LookupError("Ticket not found")
            previous = row["assignee_id"]
            await self.database.execute(
                "UPDATE tickets SET assignee_id = ?, status = ?, updated_at = ? WHERE id = ?",
                (staff_id, TicketStatus.CLAIMED, iso(), ticket_id),
            )
            await self.database.execute(
                """
                INSERT INTO ticket_assignments(
                    ticket_id, assigned_to, assigned_by, previous_assignee, created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (ticket_id, staff_id, staff_id, previous, iso()),
            )
        await self.add_event(ticket_id, "CLAIMED", staff_id, {"previous_assignee": previous})
        ticket = await self.get(ticket_id)
        if ticket is None:
            raise RuntimeError("Ticket vanished after claim")
        return ticket

    async def unclaim(self, ticket_id: int, staff_id: int) -> TicketRecord:
        previous = await self.get(ticket_id)
        if previous is None:
            raise LookupError("Ticket not found")
        await self.database.execute(
            "UPDATE tickets SET assignee_id = NULL, status = ?, updated_at = ? WHERE id = ?",
            (TicketStatus.OPEN, iso(), ticket_id),
        )
        await self.database.execute(
            """
            INSERT INTO ticket_assignments(ticket_id, assigned_to, assigned_by, previous_assignee, created_at)
            VALUES (?, NULL, ?, ?, ?)
            """,
            (ticket_id, staff_id, previous.assignee_id, iso()),
        )
        await self.add_event(ticket_id, "UNCLAIMED", staff_id, {})
        ticket = await self.get(ticket_id)
        if ticket is None:
            raise RuntimeError("Ticket vanished after unclaim")
        return ticket

    async def add_participant(self, ticket_id: int, user_id: int, actor_id: int) -> None:
        await self.database.execute(
            """
            INSERT OR IGNORE INTO ticket_participants(ticket_id, user_id, added_by, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (ticket_id, user_id, actor_id, iso()),
        )
        await self.add_event(ticket_id, "PARTICIPANT_ADDED", actor_id, {"user_id": user_id})

    async def remove_participant(self, ticket_id: int, user_id: int, actor_id: int) -> None:
        await self.database.execute(
            "DELETE FROM ticket_participants WHERE ticket_id = ? AND user_id = ?",
            (ticket_id, user_id),
        )
        await self.add_event(ticket_id, "PARTICIPANT_REMOVED", actor_id, {"user_id": user_id})

    async def create_information_request(
        self,
        ticket_id: int,
        requested_by: int,
        requested_fields: list[str],
        custom_question: str | None,
    ) -> InformationRequest:
        now = utcnow()
        cursor = await self.database.execute(
            """
            INSERT INTO information_requests(
                ticket_id, requested_by, requested_fields_json, custom_question, status, created_at
            ) VALUES (?, ?, ?, ?, 'OPEN', ?)
            """,
            (ticket_id, requested_by, dump_json(requested_fields), custom_question, iso(now)),
        )
        request = InformationRequest(
            id=int(cursor.lastrowid),
            ticket_id=ticket_id,
            requested_by=requested_by,
            requested_fields=requested_fields,
            custom_question=custom_question,
            response=None,
            status="OPEN",
            created_at=now,
        )
        await self.set_status(ticket_id, TicketStatus.WAITING_ON_MEMBER, requested_by)
        await self.add_event(
            ticket_id,
            "INFORMATION_REQUESTED",
            requested_by,
            {"request_id": request.id, "fields": requested_fields, "custom_question": custom_question},
        )
        return request

    async def get_latest_open_information_request(self, ticket_id: int) -> InformationRequest | None:
        row = await self.database.fetchone(
            """
            SELECT * FROM information_requests
            WHERE ticket_id = ? AND status = 'OPEN' ORDER BY id DESC LIMIT 1
            """,
            (ticket_id,),
        )
        if row is None:
            return None
        return InformationRequest(
            id=int(row["id"]),
            ticket_id=int(row["ticket_id"]),
            requested_by=int(row["requested_by"]),
            requested_fields=load_json(row["requested_fields_json"], []),
            custom_question=row["custom_question"],
            response=row["response"],
            status=str(row["status"]),
            created_at=parse_dt(row["created_at"]) or utcnow(),
            responded_at=parse_dt(row["responded_at"]),
        )

    async def respond_to_information_request(self, request_id: int, member_id: int, response: str) -> None:
        row = await self.database.fetchone(
            "SELECT ticket_id, status FROM information_requests WHERE id = ?",
            (request_id,),
        )
        if row is None or str(row["status"]) != "OPEN":
            raise LookupError("There is no open information request")
        ticket_id = int(row["ticket_id"])
        await self.database.execute(
            """
            UPDATE information_requests SET response = ?, status = 'RESPONDED', responded_at = ?
            WHERE id = ?
            """,
            (response, iso(), request_id),
        )
        await self.set_status(ticket_id, TicketStatus.INVESTIGATING, member_id)
        await self.add_event(
            ticket_id,
            "INFORMATION_RESPONSE",
            member_id,
            {"request_id": request_id, "response": response},
        )

    async def close(
        self,
        ticket_id: int,
        actor_id: int,
        resolution_type: ResolutionType,
        closure_reason: str,
        user_resolution: str | None,
        internal_note: str | None,
        delete_after_hours: int,
    ) -> TicketRecord:
        now = utcnow()
        delete_after = now + timedelta(hours=delete_after_hours)
        await self.database.execute(
            """
            UPDATE tickets SET status = 'CLOSED', closure_reason = ?, resolution_type = ?,
                user_resolution = ?, internal_note = ?, closed_at = ?, delete_after = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                closure_reason,
                resolution_type,
                user_resolution,
                internal_note,
                iso(now),
                iso(delete_after),
                iso(now),
                ticket_id,
            ),
        )
        await self.add_event(
            ticket_id,
            "CLOSED",
            actor_id,
            {
                "resolution_type": resolution_type,
                "closure_reason": closure_reason,
                "user_resolution": user_resolution,
            },
        )
        ticket = await self.get(ticket_id)
        if ticket is None:
            raise RuntimeError("Ticket vanished after closure")
        return ticket

    async def due_for_channel_deletion(self) -> list[TicketRecord]:
        rows = await self.database.fetchall(
            """
            SELECT * FROM tickets
            WHERE status = 'CLOSED' AND channel_id IS NOT NULL AND delete_after <= ?
            """,
            (iso(),),
        )
        return [self._row_to_ticket(row) for row in rows]

    async def clear_channel_id(self, ticket_id: int) -> None:
        await self.database.execute(
            "UPDATE tickets SET channel_id = NULL, updated_at = ? WHERE id = ?",
            (iso(), ticket_id),
        )

    async def add_evidence_record(
        self,
        ticket_id: int,
        *,
        safe_name: str,
        original_name: str,
        message_id: int | None,
        content_type: str | None,
        size: int,
        media_kind: str | None,
    ) -> None:
        await self.database.execute(
            """
            INSERT INTO ticket_evidence(
                ticket_id, safe_name, original_name, message_id, content_type, size, media_kind, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (ticket_id, safe_name, original_name, message_id, content_type, size, media_kind, iso()),
        )

    async def add_transcript(
        self,
        ticket_id: int,
        html_path: str,
        json_path: str,
        structured_json_path: str,
        log_message_id: int | None,
    ) -> None:
        await self.database.execute(
            """
            INSERT INTO transcripts(
                ticket_id, html_path, json_path, structured_json_path, log_message_id, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (ticket_id, html_path, json_path, structured_json_path, log_message_id, iso()),
        )
