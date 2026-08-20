from __future__ import annotations

from kingdom_tech_desk.models.core import IssueCategory, Severity


class SeverityService:
    def suggest(self, data: dict[str, object], similar_reports: int = 0) -> Severity:
        category = str(data.get("category", ""))
        scope = str(data.get("affected_scope", ""))
        frequency = str(data.get("frequency", ""))
        text = " ".join(str(data.get(key, "")) for key in ("title", "actual", "category_detail")).lower()

        widespread_access = scope == "everyone" and category in {
            IssueCategory.JOIN_DISCONNECT,
            IssueCategory.PROXY_TRANSFER,
        }
        widespread_loss = scope in {"everyone", "several"} and any(
            phrase in text for phrase in ("lost inventory", "data loss", "balance reset", "items disappeared")
        )
        if widespread_access or widespread_loss or similar_reports >= 3:
            return Severity.CRITICAL

        if category in {
            IssueCategory.CRASH,
            IssueCategory.JOIN_DISCONNECT,
            IssueCategory.INVENTORY_LOSS,
        } and frequency in {"every_time", "sometimes"}:
            return Severity.HIGH
        if any(phrase in text for phrase in ("cannot join", "completely blocked", "currency lost", "items lost")):
            return Severity.HIGH
        if category == IssueCategory.VISUAL:
            return Severity.LOW
        return Severity.NORMAL
