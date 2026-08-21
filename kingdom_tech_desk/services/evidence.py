from __future__ import annotations

import logging
import uuid
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from kingdom_tech_desk.constants import ALLOWED_IMAGE_EXTENSIONS, ALLOWED_VIDEO_EXTENSIONS
from kingdom_tech_desk.database.repositories.drafts import DraftRepository
from kingdom_tech_desk.models.core import EvidenceRecord
from kingdom_tech_desk.services.security import safe_child_path

LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class EvidenceSaveResult:
    records: list[EvidenceRecord] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def sniff_media_kind(payload: bytes, extension: str, declared_content_type: str | None) -> str | None:
    extension = extension.lower()
    declared = (declared_content_type or "").lower()
    if payload.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image" if extension == ".png" and (not declared or declared.startswith("image/")) else None
    if payload.startswith(b"\xff\xd8\xff"):
        return "image" if extension in {".jpg", ".jpeg"} and (not declared or declared.startswith("image/")) else None
    if payload.startswith((b"GIF87a", b"GIF89a")):
        return "image" if extension == ".gif" and (not declared or declared.startswith("image/")) else None
    if len(payload) >= 12 and payload[:4] == b"RIFF" and payload[8:12] == b"WEBP":
        return "image" if extension == ".webp" and (not declared or declared.startswith("image/")) else None
    if len(payload) >= 12 and payload[4:8] == b"ftyp":
        return "video" if extension in {".mp4", ".mov"} and (not declared or declared.startswith("video/")) else None
    if payload.startswith(b"\x1aE\xdf\xa3"):
        return "video" if extension in {".webm", ".mkv"} and (not declared or declared.startswith("video/")) else None
    return None


class EvidenceService:
    def __init__(self, root: Path, repository: DraftRepository, max_files: int = 3) -> None:
        self.root = root
        self.repository = repository
        self.max_files = max_files
        self.root.mkdir(parents=True, exist_ok=True)

    async def save_modal_attachments(
        self,
        draft_id: int,
        attachments: list[Any],
        automatic_limit_bytes: int,
    ) -> EvidenceSaveResult:
        result = EvidenceSaveResult()
        if len(attachments) > self.max_files:
            result.errors.append(f"A maximum of {self.max_files} evidence files is allowed.")
            attachments = attachments[: self.max_files]

        draft_dir = safe_child_path(self.root, str(draft_id))
        draft_dir.mkdir(parents=True, exist_ok=True)
        running_size = 0

        for attachment in attachments:
            original_name = Path(str(getattr(attachment, "filename", "evidence"))).name
            extension = Path(original_name).suffix.lower()
            size = int(getattr(attachment, "size", 0) or 0)
            content_type = getattr(attachment, "content_type", None)

            if extension not in ALLOWED_IMAGE_EXTENSIONS | ALLOWED_VIDEO_EXTENSIONS:
                result.errors.append(f"{original_name}: only supported image and video formats are allowed.")
                continue

            safe_name = f"{uuid.uuid4().hex}{extension}"
            if size <= 0:
                result.errors.append(f"{original_name}: Discord did not provide a valid file size.")
                continue

            if running_size + size > automatic_limit_bytes:
                record = EvidenceRecord(
                    id=None,
                    draft_id=draft_id,
                    safe_name=safe_name,
                    original_name=original_name,
                    path=None,
                    content_type=content_type,
                    size=size,
                    media_kind="image" if extension in ALLOWED_IMAGE_EXTENSIONS else "video",
                    requires_direct_upload=True,
                )
                result.records.append(await self.repository.add_evidence(record))
                result.warnings.append(
                    f"{original_name} is larger than the automatic copy allowance. Upload it inside the created ticket."
                )
                continue

            try:
                payload = await attachment.read()
            except Exception as exc:  # Discord/network exception is reported without leaking details.
                LOGGER.warning("Could not read evidence attachment %s: %s", original_name, type(exc).__name__)
                result.errors.append(f"{original_name}: the bot could not read this upload. Try attaching it again.")
                continue

            if len(payload) != size:
                size = len(payload)
            if running_size + size > automatic_limit_bytes:
                result.warnings.append(
                    f"{original_name} exceeded the automatic copy allowance after download. Upload it in the ticket."
                )
                record = EvidenceRecord(
                    id=None,
                    draft_id=draft_id,
                    safe_name=safe_name,
                    original_name=original_name,
                    path=None,
                    content_type=content_type,
                    size=size,
                    media_kind="image" if extension in ALLOWED_IMAGE_EXTENSIONS else "video",
                    requires_direct_upload=True,
                )
                result.records.append(await self.repository.add_evidence(record))
                continue

            kind = sniff_media_kind(payload[:64], extension, content_type)
            if kind is None:
                result.errors.append(
                    f"{original_name}: the file contents do not match a supported image or video format."
                )
                continue

            path = safe_child_path(draft_dir, safe_name)
            path.write_bytes(payload)
            running_size += size
            record = EvidenceRecord(
                id=None,
                draft_id=draft_id,
                safe_name=safe_name,
                original_name=original_name,
                path=path,
                content_type=content_type,
                size=size,
                media_kind=kind,
            )
            result.records.append(await self.repository.add_evidence(record))
        return result

    async def cleanup_draft(self, draft_id: int) -> None:
        records = await self.repository.list_evidence(draft_id)
        for record in records:
            if record.path:
                try:
                    record.path.unlink(missing_ok=True)
                except OSError:
                    LOGGER.warning("Could not delete evidence file %s", record.path)
        draft_dir = safe_child_path(self.root, str(draft_id))
        with suppress(OSError):
            draft_dir.rmdir()
        await self.repository.delete_evidence_rows(draft_id)
