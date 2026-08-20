from __future__ import annotations

from pathlib import Path

import pytest

from kingdom_tech_desk.database.repositories import DraftRepository
from kingdom_tech_desk.models.core import EvidenceRecord
from kingdom_tech_desk.services.evidence import EvidenceService, sniff_media_kind
from kingdom_tech_desk.services.security import safe_child_path


class FakeAttachment:
    def __init__(self, filename: str, payload: bytes, content_type: str) -> None:
        self.filename = filename
        self.payload = payload
        self.size = len(payload)
        self.content_type = content_type

    async def read(self) -> bytes:
        return self.payload


def test_image_signature_detection():
    assert sniff_media_kind(b"\x89PNG\r\n\x1a\nrest", ".png", "image/png") == "image"
    assert sniff_media_kind(b"\x89PNG\r\n\x1a\nrest", ".mp4", "video/mp4") is None


def test_video_signature_detection():
    payload = b"\x00\x00\x00\x18ftypisom" + b"x" * 20
    assert sniff_media_kind(payload, ".mp4", "video/mp4") == "video"


def test_path_traversal_is_rejected(tmp_path: Path):
    with pytest.raises(ValueError):
        safe_child_path(tmp_path / "evidence", "../../escape.txt")


@pytest.mark.asyncio
async def test_complete_report_image_is_saved_safely(database, tmp_path: Path):
    drafts = DraftRepository(database)
    draft = await drafts.create_or_get(1, 2, 24)
    service = EvidenceService(tmp_path / "evidence", drafts)
    attachment = FakeAttachment("proof.png", b"\x89PNG\r\n\x1a\n" + b"x" * 64, "image/png")
    result = await service.save_modal_attachments(draft.id, [attachment], 1024 * 1024)
    assert not result.errors
    assert len(result.records) == 1
    record = result.records[0]
    assert record.path is not None and record.path.exists()
    assert record.path.parent == (tmp_path / "evidence" / str(draft.id)).resolve()
    assert record.path.name != attachment.filename


@pytest.mark.asyncio
async def test_oversized_evidence_does_not_block_and_requests_direct_upload(database, tmp_path: Path):
    drafts = DraftRepository(database)
    draft = await drafts.create_or_get(2, 3, 24)
    service = EvidenceService(tmp_path / "evidence", drafts)
    attachment = FakeAttachment("large.png", b"\x89PNG\r\n\x1a\n" + b"x" * 128, "image/png")
    result = await service.save_modal_attachments(draft.id, [attachment], 32)
    assert not result.errors
    assert result.records[0].requires_direct_upload
    assert result.records[0].path is None
    assert result.warnings


@pytest.mark.asyncio
async def test_invalid_file_contents_are_rejected(database, tmp_path: Path):
    drafts = DraftRepository(database)
    draft = await drafts.create_or_get(3, 4, 24)
    service = EvidenceService(tmp_path / "evidence", drafts)
    attachment = FakeAttachment("fake.png", b"not really an image", "image/png")
    result = await service.save_modal_attachments(draft.id, [attachment], 1024)
    assert result.errors
    assert not result.records


@pytest.mark.asyncio
async def test_evidence_cleanup_removes_file_and_database_row(database, tmp_path: Path):
    drafts = DraftRepository(database)
    draft = await drafts.create_or_get(4, 5, 24)
    root = tmp_path / "evidence"
    service = EvidenceService(root, drafts)
    directory = root / str(draft.id)
    directory.mkdir(parents=True)
    path = directory / "safe.png"
    path.write_bytes(b"x")
    await drafts.add_evidence(
        EvidenceRecord(
            id=None,
            draft_id=draft.id,
            safe_name="safe.png",
            original_name="proof.png",
            path=path,
            content_type="image/png",
            size=1,
            media_kind="image",
        )
    )
    await service.cleanup_draft(draft.id)
    assert not path.exists()
    assert await drafts.list_evidence(draft.id) == []
