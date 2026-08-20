from __future__ import annotations

from dataclasses import dataclass

from kingdom_tech_desk.database.connection import Database


@dataclass(frozen=True, slots=True)
class Migration:
    version: int
    name: str
    sql: str


MIGRATIONS = [
    Migration(
        1,
        "initial_schema",
        r"""
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            applied_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
        );

        CREATE TABLE IF NOT EXISTS guild_config (
            guild_id INTEGER PRIMARY KEY,
            support_role_id INTEGER,
            escalation_role_ids_json TEXT NOT NULL DEFAULT '[]',
            open_category_id INTEGER,
            closed_category_id INTEGER,
            panel_channel_id INTEGER,
            panel_message_id INTEGER,
            log_channel_id INTEGER,
            incident_channel_id INTEGER,
            server_name TEXT NOT NULL DEFAULT 'The Kingdom',
            server_version TEXT NOT NULL DEFAULT 'Unknown',
            draft_expiry_hours INTEGER NOT NULL DEFAULT 24,
            max_open_tickets INTEGER NOT NULL DEFAULT 3,
            evidence_limit_bytes INTEGER NOT NULL DEFAULT 20971520,
            waiting_reminder_hours INTEGER NOT NULL DEFAULT 24,
            waiting_second_reminder_hours INTEGER NOT NULL DEFAULT 48,
            waiting_auto_close_hours INTEGER NOT NULL DEFAULT 72,
            closed_retention_hours INTEGER NOT NULL DEFAULT 72,
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
            updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
        );

        CREATE TABLE IF NOT EXISTS ticket_counters (
            guild_id INTEGER PRIMARY KEY,
            next_number INTEGER NOT NULL DEFAULT 1,
            updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
        );

        CREATE TABLE IF NOT EXISTS drafts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            public_id TEXT NOT NULL UNIQUE,
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            status TEXT NOT NULL,
            current_stage INTEGER NOT NULL DEFAULT 1,
            data_json TEXT NOT NULL DEFAULT '{}',
            submission_attempts INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            expires_at TEXT NOT NULL
        );

        CREATE UNIQUE INDEX IF NOT EXISTS ux_drafts_active_member
            ON drafts(guild_id, user_id)
            WHERE status IN ('ACTIVE', 'SUBMITTING');
        CREATE INDEX IF NOT EXISTS ix_drafts_expiry ON drafts(status, expires_at);

        CREATE TABLE IF NOT EXISTS draft_stage_data (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            draft_id INTEGER NOT NULL REFERENCES drafts(id) ON DELETE CASCADE,
            stage INTEGER NOT NULL,
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(draft_id, stage)
        );

        CREATE TABLE IF NOT EXISTS draft_evidence (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            draft_id INTEGER NOT NULL REFERENCES drafts(id) ON DELETE CASCADE,
            safe_name TEXT NOT NULL,
            original_name TEXT NOT NULL,
            path TEXT,
            content_type TEXT,
            size INTEGER NOT NULL,
            media_kind TEXT,
            requires_direct_upload INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS tickets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            ticket_number INTEGER NOT NULL,
            public_id TEXT NOT NULL UNIQUE,
            draft_id INTEGER REFERENCES drafts(id) ON DELETE SET NULL,
            reporter_id INTEGER NOT NULL,
            channel_id INTEGER UNIQUE,
            status TEXT NOT NULL,
            severity TEXT NOT NULL,
            assignee_id INTEGER,
            data_json TEXT NOT NULL,
            closure_reason TEXT,
            resolution_type TEXT,
            user_resolution TEXT,
            internal_note TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            closed_at TEXT,
            delete_after TEXT,
            UNIQUE(guild_id, ticket_number)
        );
        CREATE INDEX IF NOT EXISTS ix_tickets_reporter_status
            ON tickets(guild_id, reporter_id, status);
        CREATE INDEX IF NOT EXISTS ix_tickets_category_time
            ON tickets(guild_id, created_at);

        CREATE TABLE IF NOT EXISTS ticket_participants (
            ticket_id INTEGER NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
            user_id INTEGER NOT NULL,
            added_by INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY(ticket_id, user_id)
        );

        CREATE TABLE IF NOT EXISTS ticket_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticket_id INTEGER NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
            event_type TEXT NOT NULL,
            actor_id INTEGER,
            payload_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS ix_ticket_events_ticket ON ticket_events(ticket_id, id);

        CREATE TABLE IF NOT EXISTS ticket_evidence (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticket_id INTEGER NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
            safe_name TEXT NOT NULL,
            original_name TEXT NOT NULL,
            message_id INTEGER,
            content_type TEXT,
            size INTEGER NOT NULL,
            media_kind TEXT,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS ticket_assignments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticket_id INTEGER NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
            assigned_to INTEGER,
            assigned_by INTEGER NOT NULL,
            previous_assignee INTEGER,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS information_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticket_id INTEGER NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
            requested_by INTEGER NOT NULL,
            requested_fields_json TEXT NOT NULL,
            custom_question TEXT,
            response TEXT,
            status TEXT NOT NULL DEFAULT 'OPEN',
            created_at TEXT NOT NULL,
            responded_at TEXT
        );

        CREATE TABLE IF NOT EXISTS known_issues (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            public_id TEXT NOT NULL UNIQUE,
            public_title TEXT NOT NULL,
            internal_notes TEXT,
            category TEXT NOT NULL,
            affected_platforms_json TEXT NOT NULL DEFAULT '[]',
            affected_servers_json TEXT NOT NULL DEFAULT '[]',
            status TEXT NOT NULL DEFAULT 'ACTIVE',
            workaround TEXT,
            created_by INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            resolved_at TEXT
        );
        CREATE INDEX IF NOT EXISTS ix_known_issues_active ON known_issues(guild_id, status);

        CREATE TABLE IF NOT EXISTS known_issue_subscribers (
            known_issue_id INTEGER NOT NULL REFERENCES known_issues(id) ON DELETE CASCADE,
            user_id INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY(known_issue_id, user_id)
        );

        CREATE TABLE IF NOT EXISTS incidents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            public_id TEXT NOT NULL UNIQUE,
            title TEXT NOT NULL,
            category TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'OPEN',
            notes TEXT,
            created_by INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            resolved_at TEXT
        );

        CREATE TABLE IF NOT EXISTS incident_tickets (
            incident_id INTEGER NOT NULL REFERENCES incidents(id) ON DELETE CASCADE,
            ticket_id INTEGER NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
            linked_by INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY(incident_id, ticket_id)
        );

        CREATE TABLE IF NOT EXISTS transcripts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticket_id INTEGER NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
            html_path TEXT,
            json_path TEXT,
            structured_json_path TEXT,
            log_message_id INTEGER,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS rate_limits (
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            action TEXT NOT NULL,
            window_started_at TEXT NOT NULL,
            attempts INTEGER NOT NULL DEFAULT 1,
            PRIMARY KEY(guild_id, user_id, action)
        );
        """,
    ),
]


async def run_migrations(database: Database) -> None:
    await database.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            applied_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
        )
        """
    )
    rows = await database.fetchall("SELECT version FROM schema_migrations")
    applied = {int(row["version"]) for row in rows}

    for migration in MIGRATIONS:
        if migration.version in applied:
            continue
        async with database.transaction():
            # executescript commits implicitly in sqlite, so issue statements one at a time.
            statements = [statement.strip() for statement in migration.sql.split(";") if statement.strip()]
            for statement in statements:
                await database.execute(statement)
            await database.execute(
                "INSERT INTO schema_migrations(version, name) VALUES (?, ?)",
                (migration.version, migration.name),
            )
