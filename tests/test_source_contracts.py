from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def source(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_ticket_permission_overwrites_deny_everyone():
    text = source("kingdom_tech_desk/tickets/permissions.py")
    assert "guild.default_role" in text
    assert "view_channel=False" in text


def test_staff_controls_require_staff_check():
    text = source("kingdom_tech_desk/tickets/controls.py")
    assert "require_staff(interaction)" in text
    for custom_id in ("TICKET_CLAIM_ID", "TICKET_CLOSE_ID", "TICKET_REQUEST_INFO_ID"):
        assert custom_id in text


def test_persistent_views_have_timeout_none_and_static_custom_ids():
    intake = source("kingdom_tech_desk/intake/views.py")
    controls = source("kingdom_tech_desk/tickets/controls.py")
    bot = source("kingdom_tech_desk/bot.py")
    assert "super().__init__(timeout=None)" in intake
    assert "super().__init__(timeout=None)" in controls
    assert "self.add_view(PublicPanelView())" in bot
    assert "self.add_view(TicketControlsView())" in bot


def test_ticket_king_resources_are_not_managed_by_setup():
    setup = source("kingdom_tech_desk/commands/tech.py").lower()
    assert "ticket king" not in setup
    assert "kingdom-tech-desk" in setup
    assert "tech support • open" in setup


def test_orphan_reconciliation_is_marker_scoped():
    text = source("kingdom_tech_desk/services/cleanup.py")
    assert "TOPIC_TICKET_RE" in text
    assert "Unregistered KTD channel left untouched" in text
    assert "attach_channel" in text


def test_user_content_uses_restricted_allowed_mentions():
    files = [
        source("kingdom_tech_desk/tickets/creation.py"),
        source("kingdom_tech_desk/tickets/controls.py"),
        source("kingdom_tech_desk/intake/views.py"),
    ]
    combined = "\n".join(files)
    assert "AllowedMentions.none()" in combined
    assert "everyone=False" in combined


def test_no_todo_or_placeholder_implementation_markers():
    implementation = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (ROOT / "kingdom_tech_desk").rglob("*.py")
    ).lower()
    assert "todo" not in implementation
    assert "notimplementederror" in implementation  # Abstract interface only.
    assert "pass  #" not in implementation


def test_pterodactyl_egg_uses_python_312_and_no_port():
    text = source("pterodactyl/egg-kingdom-tech-desk.json")
    assert "python_3.12" in text
    assert "bash scripts/start.sh" in text
    assert "allocations" not in text.lower()

def test_persistent_component_custom_ids_are_globally_unique():
    from kingdom_tech_desk import constants

    identifiers = {
        name: value
        for name, value in vars(constants).items()
        if name.endswith("_ID") and isinstance(value, str) and value.startswith("ktd:")
    }
    assert identifiers
    duplicates = {
        value: sorted(name for name, candidate in identifiers.items() if candidate == value)
        for value in identifiers.values()
        if list(identifiers.values()).count(value) > 1
    }
    assert duplicates == {}

def test_failed_partial_ticket_channels_are_cleaned_before_retry():
    text = source("kingdom_tech_desk/tickets/creation.py")
    assert "existing.status != TicketStatus.CREATION_FAILED" in text
    assert "Cleaning up failed technical ticket" in text
    assert "await self.tickets.clear_channel_id" in text

def test_repair_checks_writable_storage_and_persistent_views():
    text = source("kingdom_tech_desk/commands/tech.py")
    assert "_directory_writable" in text
    assert "Persistent panel registered" in text
    assert "Persistent ticket controls registered" in text

