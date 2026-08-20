from __future__ import annotations

import re
from collections import Counter
from typing import Any

from kingdom_tech_desk.database.repositories.known_issues import KnownIssueRepository
from kingdom_tech_desk.database.repositories.tickets import TicketRepository
from kingdom_tech_desk.models.core import DuplicateMatch, TicketStatus

TOKEN_RE = re.compile(r"[a-z0-9]{2,}")
STOPWORDS = {
    "the",
    "and",
    "for",
    "that",
    "this",
    "with",
    "from",
    "when",
    "then",
    "into",
    "does",
    "not",
    "work",
    "working",
    "issue",
    "problem",
    "server",
}


class DuplicateDetectionService:
    def __init__(self, tickets: TicketRepository, known_issues: KnownIssueRepository) -> None:
        self.tickets = tickets
        self.known_issues = known_issues

    @staticmethod
    def tokens(value: str) -> set[str]:
        return {token for token in TOKEN_RE.findall(value.lower()) if token not in STOPWORDS}

    @classmethod
    def similarity(cls, left: str, right: str) -> float:
        left_tokens = cls.tokens(left)
        right_tokens = cls.tokens(right)
        if not left_tokens or not right_tokens:
            return 0.0
        return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)

    async def find_matches(
        self,
        guild_id: int,
        data: dict[str, Any],
        window_minutes: int,
        threshold: float = 0.34,
    ) -> list[DuplicateMatch]:
        title = str(data.get("title", ""))
        category = str(data.get("category", ""))
        platform = str(data.get("platform", ""))
        corpus = " ".join(
            str(data.get(key, "")) for key in ("title", "actual", "category_detail", "where_when")
        )
        matches: list[DuplicateMatch] = []

        for issue in await self.known_issues.list_active(guild_id):
            score = self.similarity(corpus, f"{issue['public_title']} {issue.get('workaround') or ''}")
            if issue["category"] == category:
                score += 0.18
            platforms = issue.get("platforms", [])
            if platform and platform in platforms:
                score += 0.08
            if score >= threshold:
                matches.append(
                    DuplicateMatch(
                        kind="known_issue",
                        id=int(issue["id"]),
                        title=str(issue["public_title"]),
                        score=min(score, 1.0),
                        status=str(issue["status"]),
                        public_id=str(issue["public_id"]),
                    )
                )

        for ticket in await self.tickets.list_recent(guild_id, window_minutes):
            if ticket.status in {TicketStatus.CLOSED, TicketStatus.CREATION_FAILED}:
                continue
            score = self.similarity(corpus, " ".join(str(ticket.data.get(k, "")) for k in ("title", "actual")))
            if str(ticket.data.get("category", "")) == category:
                score += 0.18
            if str(ticket.data.get("platform", "")) == platform:
                score += 0.05
            if score >= threshold:
                matches.append(
                    DuplicateMatch(
                        kind="ticket",
                        id=ticket.id,
                        title=str(ticket.data.get("title", f"Ticket {ticket.ticket_number}")),
                        score=min(score, 1.0),
                        status=ticket.status,
                        public_id=f"KTS-{ticket.ticket_number:06d}",
                    )
                )

        return sorted(matches, key=lambda match: match.score, reverse=True)[:5]

    async def count_similar_recent(
        self,
        guild_id: int,
        data: dict[str, Any],
        window_minutes: int,
        threshold: float = 0.34,
    ) -> int:
        matches = await self.find_matches(guild_id, data, window_minutes, threshold)
        return sum(1 for match in matches if match.kind == "ticket")

    @classmethod
    def cluster_keywords(cls, reports: list[str], limit: int = 8) -> list[str]:
        counter: Counter[str] = Counter()
        for report in reports:
            counter.update(cls.tokens(report))
        return [token for token, _count in counter.most_common(limit)]
