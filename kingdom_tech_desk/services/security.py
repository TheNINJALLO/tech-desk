from __future__ import annotations

import html
import re
import unicodedata
from pathlib import Path

CHANNEL_SAFE_RE = re.compile(r"[^a-z0-9-]+")
MULTI_HYPHEN_RE = re.compile(r"-{2,}")
MARKDOWN_SPECIAL_RE = re.compile(r"([\\`*_{}\[\]()#+\-.!|>~])")


def neutralize_mentions(value: str) -> str:
    return value.replace("@", "@\u200b")


def escape_markdown(value: str) -> str:
    return MARKDOWN_SPECIAL_RE.sub(r"\\\1", neutralize_mentions(value))


def sanitize_channel_component(value: str, fallback: str = "member", max_length: int = 35) -> str:
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii").lower()
    normalized = normalized.replace("_", "-").replace(" ", "-")
    normalized = CHANNEL_SAFE_RE.sub("-", normalized)
    normalized = MULTI_HYPHEN_RE.sub("-", normalized).strip("-")
    return (normalized or fallback)[:max_length].strip("-") or fallback


def ticket_channel_name(number: int, gamertag: str) -> str:
    return f"tech-{number:06d}-{sanitize_channel_component(gamertag)}"[:100]


def safe_child_path(root: Path, filename: str) -> Path:
    candidate = (root / filename).resolve()
    resolved_root = root.resolve()
    if candidate != resolved_root and resolved_root not in candidate.parents:
        raise ValueError("Path escaped the configured storage directory")
    return candidate


def html_text(value: str) -> str:
    return html.escape(value, quote=True)


def is_tech_desk_resource(name: str, topic: str | None = None) -> bool:
    lowered = name.lower()
    topic_lowered = (topic or "").lower()
    return (
        lowered.startswith("tech-")
        or lowered.startswith("tech-support")
        or lowered in {"tech-ticket-logs", "tech-incidents"}
        or "kingdom-tech-desk" in topic_lowered
        or "ktd-managed" in topic_lowered
    )


def is_ticket_king_resource(name: str, topic: str | None = None) -> bool:
    text = f"{name} {topic or ''}".lower()
    return "ticket king" in text or "ticket-king" in text or "ticketking" in text
