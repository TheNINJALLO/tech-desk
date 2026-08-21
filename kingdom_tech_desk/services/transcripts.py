from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import asdict
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

from kingdom_tech_desk.database.repositories.common import iso
from kingdom_tech_desk.models.core import TicketRecord
from kingdom_tech_desk.services.security import safe_child_path


class TranscriptService:
    def __init__(self, output_dir: Path, template_dir: Path | None = None) -> None:
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)
        template_path = template_dir or Path(__file__).resolve().parent.parent / "templates"
        self.environment = Environment(
            loader=FileSystemLoader(str(template_path)),
            autoescape=select_autoescape(["html", "xml"]),
            trim_blocks=True,
            lstrip_blocks=True,
        )

    @staticmethod
    def serialize_message(message: Any) -> dict[str, Any]:
        author = getattr(message, "author", None)
        attachments = []
        for attachment in getattr(message, "attachments", []) or []:
            attachments.append(
                {
                    "id": int(getattr(attachment, "id", 0) or 0),
                    "filename": str(getattr(attachment, "filename", "attachment")),
                    "size": int(getattr(attachment, "size", 0) or 0),
                    "content_type": getattr(attachment, "content_type", None),
                    "url": str(getattr(attachment, "url", "")),
                }
            )
        embeds = []
        for embed in getattr(message, "embeds", []) or []:
            try:
                embeds.append(embed.to_dict())
            except AttributeError:
                embeds.append({"description": str(embed)})
        created_at = getattr(message, "created_at", None)
        return {
            "id": int(getattr(message, "id", 0) or 0),
            "author_id": int(getattr(author, "id", 0) or 0),
            "author_name": str(getattr(author, "display_name", getattr(author, "name", "Unknown"))),
            "author_bot": bool(getattr(author, "bot", False)),
            "content": str(getattr(message, "content", "") or ""),
            "created_at": created_at.isoformat() if created_at else "",
            "edited_at": (
                getattr(message, "edited_at", None).isoformat()
                if getattr(message, "edited_at", None)
                else None
            ),
            "attachments": attachments,
            "embeds": embeds,
        }

    def create(
        self,
        ticket: TicketRecord,
        messages: Iterable[Any],
        events: list[dict[str, Any]],
    ) -> tuple[Path, Path, Path]:
        serialized_messages = [
            message if isinstance(message, dict) else self.serialize_message(message) for message in messages
        ]
        display_id = f"KTS-{ticket.ticket_number:06d}"
        stem = f"{display_id.lower()}-{ticket.id}"
        ticket_dir = safe_child_path(self.output_dir, str(ticket.guild_id))
        ticket_dir.mkdir(parents=True, exist_ok=True)
        html_path = safe_child_path(ticket_dir, f"{stem}.html")
        json_path = safe_child_path(ticket_dir, f"{stem}.json")
        structured_path = safe_child_path(ticket_dir, f"{stem}-intake.json")

        ticket_payload = asdict(ticket)
        for key, value in list(ticket_payload.items()):
            if hasattr(value, "isoformat"):
                ticket_payload[key] = value.isoformat()
            elif hasattr(value, "value"):
                ticket_payload[key] = value.value

        archive = {
            "schema_version": 1,
            "generated_at": iso(),
            "display_id": display_id,
            "ticket": ticket_payload,
            "messages": serialized_messages,
            "events": events,
        }
        json_path.write_text(json.dumps(archive, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
        structured_path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "display_id": display_id,
                    "ticket_id": ticket.id,
                    "guild_id": ticket.guild_id,
                    "reporter_id": ticket.reporter_id,
                    "status": str(ticket.status),
                    "severity": str(ticket.severity),
                    "intake": ticket.data,
                },
                indent=2,
                ensure_ascii=False,
                default=str,
            ),
            encoding="utf-8",
        )

        template = self.environment.get_template("transcript.html.j2")
        html_path.write_text(
            template.render(
                display_id=display_id,
                ticket=ticket_payload,
                messages=serialized_messages,
                events=events,
            ),
            encoding="utf-8",
        )
        return html_path, json_path, structured_path
