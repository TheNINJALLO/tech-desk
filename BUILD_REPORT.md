# Kingdom Tech Desk v1.0.0 Build Report

Build date: 2026-08-20

## Delivered

- Standalone Discord technical-support bot that does not modify or depend on Ticket King
- Components V2 public support panel
- Three-stage, restart-safe technical report wizard
- Deterministic written-detail validation with repairable drafts
- Optional image/video evidence with extension and file-signature checks
- Known issues, duplicate suggestions, subscriptions, and incident clustering
- Private ticket channels and persistent staff controls
- Information requests, participants, severity, status, escalation, resolution, and closure
- HTML, JSON, and structured-intake transcripts
- SQLite migrations, WAL mode, backups, cleanup, and startup reconciliation
- Optional non-blocking OniLink server-context adapter contract
- Local, Docker, and Pterodactyl deployment files
- Python wheel and complete source archive

## Verification completed

- `pytest -q`: 50 tests passed
- `python -m compileall -q kingdom_tech_desk tests`: passed
- Pterodactyl egg JSON parsing: passed
- Package wheel build: passed
- Wheel contains the transcript template and console entry point
- Portable relative-path configuration smoke test: passed
- Persistent component custom-ID uniqueness regression test: passed
- Concurrent draft submission and ticket counter tests: passed
- Evidence path traversal and file-signature tests: passed

## Runtime verification boundary

This build environment did not contain a Discord bot token or access to the target Discord guild, so the bot was not connected to Discord and no live channels were created here. The optional OniLink adapter was also left disabled because no concrete OniLink HTTP endpoint was supplied. The automated suite covers the local validation, storage, evidence, transcript, persistence, permission-contract, and lifecycle logic.

## First run

1. Copy `.env.example` to `.env` and set `DISCORD_TOKEN`.
2. Copy `config.example.yaml` to `config.yaml`.
3. Install `requirements.txt` or import the included Pterodactyl egg.
4. Start the bot with `python -m kingdom_tech_desk`.
5. In Discord, run `/tech setup`.
6. Use `/tech repair` to verify permissions, storage, intents, persistent controls, and managed resources.
