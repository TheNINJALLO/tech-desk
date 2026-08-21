from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from typing import Any

from kingdom_tech_desk.database.connection import Database
from kingdom_tech_desk.database.repositories.common import (
    dump_json,
    iso,
    load_json,
    parse_dt,
    public_id,
    utcnow,
)
from kingdom_tech_desk.models.core import DraftRecord, DraftStage, DraftStatus, EvidenceRecord


class DraftRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def _row_to_draft(self, row: Any) -> DraftRecord:
        return DraftRecord(
            id=int(row["id"]),
            public_id=str(row["public_id"]),
            guild_id=int(row["guild_id"]),
            user_id=int(row["user_id"]),
            status=DraftStatus(str(row["status"])),
            current_stage=DraftStage(int(row["current_stage"])),
            data=load_json(row["data_json"], {}),
            created_at=parse_dt(row["created_at"]) or utcnow(),
            updated_at=parse_dt(row["updated_at"]) or utcnow(),
            expires_at=parse_dt(row["expires_at"]) or utcnow(),
            submission_attempts=int(row["submission_attempts"]),
        )

    async def get(self, draft_id: int) -> DraftRecord | None:
        row = await self.database.fetchone("SELECT * FROM drafts WHERE id = ?", (draft_id,))
        return self._row_to_draft(row) if row else None

    async def get_by_public_id(self, value: str) -> DraftRecord | None:
        row = await self.database.fetchone("SELECT * FROM drafts WHERE public_id = ?", (value,))
        return self._row_to_draft(row) if row else None

    async def get_active(self, guild_id: int, user_id: int) -> DraftRecord | None:
        row = await self.database.fetchone(
            """
            SELECT * FROM drafts
            WHERE guild_id = ? AND user_id = ? AND status IN ('ACTIVE', 'SUBMITTING')
            ORDER BY id DESC LIMIT 1
            """,
            (guild_id, user_id),
        )
        if row is None:
            return None
        draft = self._row_to_draft(row)
        if draft.expires_at <= utcnow() and draft.status == DraftStatus.ACTIVE:
            await self.set_status(draft.id, DraftStatus.EXPIRED)
            return None
        return draft

    async def create_or_get(self, guild_id: int, user_id: int, expiry_hours: int) -> DraftRecord:
        existing = await self.get_active(guild_id, user_id)
        if existing:
            return existing

        now = utcnow()
        expires = now + timedelta(hours=expiry_hours)
        identifier = public_id("DRAFT")
        try:
            cursor = await self.database.execute(
                """
                INSERT INTO drafts(
                    public_id, guild_id, user_id, status, current_stage, data_json,
                    created_at, updated_at, expires_at
                ) VALUES (?, ?, ?, ?, ?, '{}', ?, ?, ?)
                """,
                (
                    identifier,
                    guild_id,
                    user_id,
                    DraftStatus.ACTIVE,
                    DraftStage.CONTEXT,
                    iso(now),
                    iso(now),
                    iso(expires),
                ),
            )
            draft_id = int(cursor.lastrowid)
        except Exception:
            # A simultaneous button press may have won the partial unique-index race.
            existing = await self.get_active(guild_id, user_id)
            if existing:
                return existing
            raise
        draft = await self.get(draft_id)
        if draft is None:
            raise RuntimeError("Draft insert succeeded but the row could not be read")
        return draft

    async def save_stage(
        self,
        draft_id: int,
        stage: DraftStage,
        values: dict[str, Any],
        expiry_hours: int,
    ) -> DraftRecord:
        now = utcnow()
        async with self.database.transaction():
            row = await self.database.fetchone("SELECT * FROM drafts WHERE id = ?", (draft_id,))
            if row is None:
                raise LookupError("Draft no longer exists")
            draft = self._row_to_draft(row)
            if draft.status not in {DraftStatus.ACTIVE, DraftStatus.SUBMITTING}:
                raise RuntimeError(f"Draft is not editable while {draft.status}")
            merged = dict(draft.data)
            merged.update(values)
            next_stage = DraftStage(min(int(stage) + 1, int(DraftStage.COMPLETE)))
            expires = now + timedelta(hours=expiry_hours)
            await self.database.execute(
                """
                UPDATE drafts SET data_json = ?, current_stage = ?, status = 'ACTIVE',
                    updated_at = ?, expires_at = ? WHERE id = ?
                """,
                (dump_json(merged), int(next_stage), iso(now), iso(expires), draft_id),
            )
            await self.database.execute(
                """
                INSERT INTO draft_stage_data(draft_id, stage, payload_json, created_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(draft_id, stage) DO UPDATE SET
                    payload_json = excluded.payload_json,
                    created_at = excluded.created_at
                """,
                (draft_id, int(stage), dump_json(values), iso(now)),
            )
        updated = await self.get(draft_id)
        if updated is None:
            raise RuntimeError("Draft vanished after stage save")
        return updated

    async def patch_data(
        self,
        draft_id: int,
        values: dict[str, Any],
        *,
        current_stage: DraftStage | None = None,
        expiry_hours: int | None = None,
    ) -> DraftRecord:
        now = utcnow()
        async with self.database.transaction():
            row = await self.database.fetchone("SELECT * FROM drafts WHERE id = ?", (draft_id,))
            if row is None:
                raise LookupError("Draft no longer exists")
            draft = self._row_to_draft(row)
            merged = dict(draft.data)
            merged.update(values)
            stage = int(current_stage or draft.current_stage)
            expires = draft.expires_at if expiry_hours is None else now + timedelta(hours=expiry_hours)
            await self.database.execute(
                "UPDATE drafts SET data_json = ?, current_stage = ?, updated_at = ?, expires_at = ? WHERE id = ?",
                (dump_json(merged), stage, iso(now), iso(expires), draft_id),
            )
        updated = await self.get(draft_id)
        if updated is None:
            raise RuntimeError("Draft vanished after update")
        return updated

    async def increment_attempts(self, draft_id: int) -> None:
        await self.database.execute(
            """
            UPDATE drafts SET submission_attempts = submission_attempts + 1, updated_at = ?
            WHERE id = ?
            """,
            (iso(), draft_id),
        )

    async def claim_for_submission(self, draft_id: int) -> bool:
        async with self.database.transaction():
            row = await self.database.fetchone("SELECT status FROM drafts WHERE id = ?", (draft_id,))
            if row is None or str(row["status"]) != DraftStatus.ACTIVE:
                return False
            await self.database.execute(
                "UPDATE drafts SET status = 'SUBMITTING', updated_at = ? WHERE id = ? AND status = 'ACTIVE'",
                (iso(), draft_id),
            )
            changed = await self.database.fetchone("SELECT changes() AS count")
            return bool(changed and int(changed["count"]) == 1)

    async def release_submission_claim(self, draft_id: int) -> None:
        await self.database.execute(
            "UPDATE drafts SET status = 'ACTIVE', updated_at = ? WHERE id = ? AND status = 'SUBMITTING'",
            (iso(), draft_id),
        )

    async def set_status(self, draft_id: int, status: DraftStatus) -> None:
        await self.database.execute(
            "UPDATE drafts SET status = ?, updated_at = ? WHERE id = ?",
            (status, iso(), draft_id),
        )

    async def expire_due(self) -> list[int]:
        rows = await self.database.fetchall(
            """
            SELECT DISTINCT d.id
            FROM drafts AS d
            LEFT JOIN draft_evidence AS e ON e.draft_id = d.id
            WHERE (d.status = 'ACTIVE' AND d.expires_at <= ?)
               OR (d.status = 'EXPIRED' AND e.id IS NOT NULL)
            """,
            (iso(),),
        )
        ids = [int(row["id"]) for row in rows]
        if ids:
            placeholders = ",".join("?" for _ in ids)
            await self.database.execute(
                f"UPDATE drafts SET status = 'EXPIRED', updated_at = ? WHERE id IN ({placeholders}) AND status = 'ACTIVE'",
                (iso(), *ids),
            )
        return ids

    async def list_for_user(self, guild_id: int, user_id: int) -> list[DraftRecord]:
        rows = await self.database.fetchall(
            "SELECT * FROM drafts WHERE guild_id = ? AND user_id = ? ORDER BY id",
            (guild_id, user_id),
        )
        return [self._row_to_draft(row) for row in rows]

    async def add_evidence(self, evidence: EvidenceRecord) -> EvidenceRecord:
        cursor = await self.database.execute(
            """
            INSERT INTO draft_evidence(
                draft_id, safe_name, original_name, path, content_type, size, media_kind,
                requires_direct_upload, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                evidence.draft_id,
                evidence.safe_name,
                evidence.original_name,
                str(evidence.path) if evidence.path else None,
                evidence.content_type,
                evidence.size,
                evidence.media_kind,
                int(evidence.requires_direct_upload),
                iso(),
            ),
        )
        evidence.id = int(cursor.lastrowid)
        return evidence

    async def list_evidence(self, draft_id: int) -> list[EvidenceRecord]:
        rows = await self.database.fetchall(
            "SELECT * FROM draft_evidence WHERE draft_id = ? ORDER BY id",
            (draft_id,),
        )
        return [
            EvidenceRecord(
                id=int(row["id"]),
                draft_id=int(row["draft_id"]),
                safe_name=str(row["safe_name"]),
                original_name=str(row["original_name"]),
                path=Path(str(row["path"])) if row["path"] else None,
                content_type=row["content_type"],
                size=int(row["size"]),
                media_kind=row["media_kind"],
                requires_direct_upload=bool(row["requires_direct_upload"]),
                created_at=parse_dt(row["created_at"]),
            )
            for row in rows
        ]

    async def delete_evidence_rows(self, draft_id: int) -> None:
        await self.database.execute("DELETE FROM draft_evidence WHERE draft_id = ?", (draft_id,))
