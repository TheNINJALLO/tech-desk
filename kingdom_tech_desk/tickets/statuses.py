from __future__ import annotations

from kingdom_tech_desk.models.core import TicketStatus

ALLOWED_TRANSITIONS: dict[TicketStatus, set[TicketStatus]] = {
    TicketStatus.OPEN: {
        TicketStatus.CLAIMED,
        TicketStatus.INVESTIGATING,
        TicketStatus.WAITING_ON_MEMBER,
        TicketStatus.KNOWN_ISSUE,
        TicketStatus.RESOLVED,
        TicketStatus.CLOSED,
    },
    TicketStatus.CLAIMED: {
        TicketStatus.OPEN,
        TicketStatus.INVESTIGATING,
        TicketStatus.WAITING_ON_MEMBER,
        TicketStatus.FIX_PENDING,
        TicketStatus.KNOWN_ISSUE,
        TicketStatus.RESOLVED,
        TicketStatus.CLOSED,
    },
    TicketStatus.INVESTIGATING: {
        TicketStatus.WAITING_ON_MEMBER,
        TicketStatus.FIX_PENDING,
        TicketStatus.KNOWN_ISSUE,
        TicketStatus.RESOLVED,
        TicketStatus.CLOSED,
    },
    TicketStatus.WAITING_ON_MEMBER: {
        TicketStatus.INVESTIGATING,
        TicketStatus.FIX_PENDING,
        TicketStatus.RESOLVED,
        TicketStatus.CLOSED,
    },
    TicketStatus.FIX_PENDING: {
        TicketStatus.INVESTIGATING,
        TicketStatus.KNOWN_ISSUE,
        TicketStatus.RESOLVED,
        TicketStatus.CLOSED,
    },
    TicketStatus.KNOWN_ISSUE: {
        TicketStatus.INVESTIGATING,
        TicketStatus.FIX_PENDING,
        TicketStatus.RESOLVED,
        TicketStatus.CLOSED,
    },
    TicketStatus.RESOLVED: {TicketStatus.INVESTIGATING, TicketStatus.CLOSED},
    TicketStatus.CLOSED: set(),
    TicketStatus.CREATION_FAILED: {TicketStatus.OPEN},
}


def can_transition(current: TicketStatus, target: TicketStatus) -> bool:
    return current == target or target in ALLOWED_TRANSITIONS.get(current, set())
