from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path

from kingdom_tech_desk.database.connection import Database

LOGGER = logging.getLogger(__name__)


class BackupService:
    def __init__(self, database: Database, backup_dir: Path, retention: int) -> None:
        self.database = database
        self.backup_dir = backup_dir
        self.retention = max(1, retention)
        self.backup_dir.mkdir(parents=True, exist_ok=True)

    async def create(self) -> Path:
        stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S-%f")
        destination = self.backup_dir / f"kingdom-tech-desk-{stamp}.db"
        await self.database.backup_to(destination)
        self.prune()
        return destination

    def prune(self) -> None:
        backups = sorted(self.backup_dir.glob("kingdom-tech-desk-*.db"), key=lambda path: path.stat().st_mtime)
        for old in backups[: -self.retention]:
            try:
                old.unlink()
            except OSError:
                LOGGER.warning("Could not remove old backup %s", old)
