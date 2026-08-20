# Kingdom Tech Desk

Kingdom Tech Desk is a standalone Discord technical-support ticket system for **The Kingdom** Minecraft Bedrock server. It is designed to run beside an existing general-purpose ticket bot such as Ticket King without reading, changing, renaming, or depending on that system.

The bot does not create a ticket channel when a member clicks the public button. It first walks the member through a three-stage technical report, saves each completed stage, validates the written information locally, and creates a private staff channel only after the report is useful enough to investigate.

No OpenAI, Gemini, or other paid AI API is required.

## Core behavior

- Persistent Components V2 public support panel
- Three-stage modal intake with radio groups, checkbox groups, text inputs, and optional file uploads
- One restart-safe draft per member per guild
- Prefilled correction forms when validation fails
- Deterministic validation with transparent field-specific errors
- Optional screenshots and videos that never replace written details
- Private ticket channels with explicit permission overwrites
- Claiming, status, severity, participants, escalation, information requests, incidents, duplicates, resolution, and closure controls
- Public known-issue list and subscriptions
- HTML, JSON, and structured-intake transcripts
- SQLite WAL storage, migrations, daily backups, and startup reconciliation
- Waiting-on-member reminders, automatic no-response closure, and delayed channel deletion
- Optional non-blocking OniLink server-context adapter
- Pterodactyl egg, Dockerfile, CI workflow, and test suite

## Member report flow

1. The member presses **Start Technical Report**.
2. Stage 1 records the category, platform, affected scope, gamertag, location, and approximate time.
3. Stage 2 records a useful title, exact actions, expected result, actual result, and category-specific technical details.
4. Stage 3 records frequency, troubleshooting, Minecraft version, additional details, and up to three optional media files.
5. The local validator checks every required field.
6. Invalid reports remain private drafts. No staff channel is created.
7. Valid reports are compared with current known issues and recent similar tickets.
8. The member can subscribe to a matching known issue or continue with a separate ticket.
9. An accepted report creates one private `tech-000001-gamertag` channel.

A report such as `It does not work. Watch the video.` is rejected even when a video is attached. A complete written report can pass without any media.

## Requirements

- Python 3.12 or newer
- Discord bot application and token
- SQLite, included with Python
- Network access from the bot to Discord
- Optional HTTP access to an OniLink context endpoint when that adapter is enabled

Pinned runtime packages are listed in `requirements.txt`.

## Discord application setup

1. Open the Discord Developer Portal and create an application.
2. Open **Bot**, create the bot user, and copy its token.
3. Enable **Server Members Intent**.
4. Enable **Message Content Intent** so complete channel conversations, attachment metadata, and message text can be included in transcripts.
5. Under OAuth2 URL Generator, select the `bot` and `applications.commands` scopes.
6. Grant the permissions listed below.
7. Invite the bot to the server.
8. Start the bot and run `/tech setup` as a server administrator.

### Required bot permissions

Kingdom Tech Desk does **not** require Administrator.

- View Channels
- Send Messages
- Embed Links
- Attach Files
- Read Message History
- Manage Channels
- Manage Roles
- Manage Messages

`Manage Roles` is used to edit channel permission overwrites. Keep the bot's role above the `Kingdom Tech Support` role and any role it must manage.

## Local installation

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
cp .env.example .env
cp config.example.yaml config.yaml
```

Edit `.env`:

```dotenv
DISCORD_TOKEN=your_bot_token
KTD_CONFIG=config.yaml
KTD_OWNER_IDS=123456789012345678
KTD_DEV_GUILD_ID=123456789012345678
```

For development, setting `KTD_DEV_GUILD_ID` causes commands to sync directly to one guild. Remove it for global command sync.

Start the bot:

```bash
python -m kingdom_tech_desk
```

The application also installs the console entry point:

```bash
kingdom-tech-desk
```

## Pterodactyl installation

The importable egg is located at:

```text
pterodactyl/egg-kingdom-tech-desk.json
```

### Import and create the server

1. Import the egg into a Pterodactyl nest.
2. Create a server using the **Python 3.12** image.
3. Allocate enough disk for transcripts and temporary evidence. No network allocation is required by the bot itself.
4. Enter the Discord token in the protected `DISCORD_TOKEN` variable.
5. Set `KTD_OWNER_IDS` when owner-level access is needed.
6. Either configure `GIT_REPO` and `GIT_BRANCH`, or upload this project into `/home/container`.
7. Start the server.
8. Run `/tech setup` in Discord.

The startup script creates `.venv`, installs dependencies only when `requirements.txt` changes, creates storage directories, and launches the module. The database, evidence, transcripts, backups, configuration, and logs remain outside application updates.

### Pterodactyl paths

```text
/home/container/config.yaml
/home/container/data/kingdom_tech_desk.db
/home/container/data/evidence/
/home/container/data/transcripts/
/home/container/data/backups/
/home/container/logs/
```

## First-run setup

Run:

```text
/tech setup
```

The setup command creates or binds resources owned by Kingdom Tech Desk:

- `Kingdom Tech Support` role
- `TECH SUPPORT • OPEN` category
- `TECH SUPPORT • CLOSED` category
- `#tech-support` public panel channel
- `#tech-ticket-logs` private transcript channel
- `#tech-incidents` private incident channel

Managed text channels contain the `kingdom-tech-desk` topic marker. Startup reconciliation and repair logic only act on stored IDs or channels carrying that marker. Ticket King resources are not inspected or modified.

## Commands

### Main commands

| Command | Purpose |
|---|---|
| `/tech setup` | Create or bind the required role, categories, channels, and panel |
| `/tech stats` | Show status, severity, and draft counts |
| `/tech repair` | Check permissions, storage, intents, channel records, and persistent resources |
| `/tech export` | Export non-secret guild configuration, statistics, known issues, and incidents |
| `/tech privacy-delete` | Remove drafts and anonymize a member's closed ticket records |

### Panel commands

| Command | Purpose |
|---|---|
| `/tech panel send` | Post a new public technical-support panel |
| `/tech panel refresh` | Reattach the current persistent panel view |

### Configuration commands

| Command | Purpose |
|---|---|
| `/tech config view` | Display guild configuration |
| `/tech config support-role` | Set the support role |
| `/tech config escalation-role` | Add an escalation role |
| `/tech config open-category` | Set the private open category |
| `/tech config closed-category` | Set the archive category |
| `/tech config log-channel` | Set the transcript channel |
| `/tech config server` | Set the server name included in reports |
| `/tech config server-version` | Set the current BDS/server version |
| `/tech config draft-expiry` | Set draft retention from 1 to 168 hours |
| `/tech config inactivity` | Set reminder, waiting auto-close, and archive-retention timings |
| `/tech config max-open` | Set the per-member open-ticket limit |
| `/tech config evidence-limit` | Set automatic media-copy allowance in MiB |

### Known-issue commands

| Command | Purpose |
|---|---|
| `/tech known add` | Add a public known issue with optional workaround and internal notes |
| `/tech known update` | Update the public title, workaround, or internal notes |
| `/tech known resolve` | Resolve a known issue |
| `/tech known list` | Display public active known issues |
| `/tech known subscribe` | Subscribe the invoking member to an issue |

### Incident commands

| Command | Purpose |
|---|---|
| `/tech incident create` | Create a master incident |
| `/tech incident list` | List active incidents |
| `/tech incident resolve` | Resolve an incident |
| `/tech incident link` | Link a ticket number to an incident |

## Staff controls inside tickets

The accepted ticket message has restart-safe controls:

- Claim and Unclaim
- Request Information
- Change Status
- Change Severity
- Add Member and Remove Member
- Escalate
- Link Incident
- Mark Duplicate
- Resolve
- Close

Only configured support roles, escalation roles, administrators, or configured owner IDs can use staff controls.

### Ticket statuses

- `OPEN`
- `CLAIMED`
- `INVESTIGATING`
- `WAITING_ON_MEMBER`
- `FIX_PENDING`
- `KNOWN_ISSUE`
- `RESOLVED`
- `CLOSED`

### Information requests

Staff select exactly what is missing, add an optional custom question, and place the ticket in `WAITING_ON_MEMBER`. The reporter receives a member-only **Provide Requested Information** button. The answer is stored in SQLite, posted into the channel, and moves the ticket back to `INVESTIGATING`.

## Validation rules

The validator normalizes Unicode, whitespace, line endings, Markdown noise, mentions, URLs for word-count purposes, and repeated punctuation. Original answers remain stored unchanged.

Hard checks include:

- Title has at least 12 meaningful characters and three meaningful words.
- Reproduction steps have at least 60 meaningful characters.
- At least two distinct actions are detected.
- Expected result has at least 15 meaningful characters.
- Actual result has at least 35 meaningful characters.
- Expected and actual results are not identical or near duplicates.
- Category-specific detail has at least 20 meaningful characters.
- Location and time has at least 15 meaningful characters.
- Minecraft version is numeric, or `unknown` includes a reason.
- At least one troubleshooting option is selected.
- `Nothing attempted yet` is mutually exclusive.
- Written fields contain at least 45 meaningful words by default.
- Required fields are not dominated by phrases such as `broken`, `doesn't work`, `watch the video`, or `idk`.
- The same paragraph cannot be pasted into several different fields.

Validation errors identify the exact field, explain why it failed, and reopen the earliest failed stage with previous values prefilled.

## Evidence handling

Supported images:

```text
.png .jpg .jpeg .webp .gif
```

Supported videos:

```text
.mp4 .mov .webm .mkv
```

The bot checks both the filename extension and file signature. User filenames are never used as storage paths. Temporary files receive random safe names inside the configured evidence directory.

By default:

- Up to three files can be selected.
- Up to 20 MiB combined is copied automatically.
- Oversized evidence does not block a valid written report.
- The accepted ticket asks the member to upload oversized files directly.
- Temporary copies are removed after ticket creation, cancellation, or draft expiration.

The bot never extracts, executes, shell-opens, or interprets uploaded media as code.

## Ticket closure and transcripts

Closing requires a resolution type and reason. Optional member-facing and internal notes may also be supplied.

Resolution types:

- `FIXED`
- `WORKAROUND_PROVIDED`
- `KNOWN_ISSUE`
- `DUPLICATE`
- `USER_ERROR`
- `UNABLE_TO_REPRODUCE`
- `NO_RESPONSE`
- `NOT_A_TECHNICAL_ISSUE`
- `OTHER`

The closure service creates:

- Human-readable HTML transcript
- Machine-readable JSON archive
- Structured intake JSON
- Ticket event timeline

Files are saved locally and uploaded to the configured log channel. The channel is locked, moved to the closed category, and deleted after the configured retention period. Transcript and ticket database records are preserved when the Discord channel is removed.

## Lifecycle defaults

- Draft expiry: 24 hours
- First waiting-on-member reminder: 24 hours
- Second reminder: 48 hours
- Automatic no-response closure: 72 hours
- Closed-channel retention: 72 hours
- Daily database backup retention: 14 backups

`INVESTIGATING` and `FIX_PENDING` tickets are not automatically closed by the waiting-on-member lifecycle.

## SQLite and backups

SQLite is configured with:

- WAL journal mode
- Foreign keys
- Normal synchronous mode
- Five-second busy timeout
- Immediate transactions for counters and submission claims

Daily backups are written to `data/backups/` with timestamped filenames.

### Manual backup

Stop the bot, then copy:

```text
data/kingdom_tech_desk.db
```

For a live installation, use one of the consistent backup files already created in `data/backups/`.

### Restore

1. Stop the bot.
2. Move the current database somewhere safe.
3. Copy the selected backup to the configured database path.
4. Start the bot.
5. Run `/tech repair`.

Migrations run automatically at startup.

## Updating

Git installations can run:

```bash
bash scripts/update.sh
```

The update uses a fast-forward-only merge and invalidates the dependency marker so changed requirements install on the next start.

For ZIP installations, stop the bot and replace application files while preserving:

```text
config.yaml
.env
data/
logs/
.venv/
```

Never overwrite or delete the live database during an application update.

## Optional OniLink server context

The bot includes a clean `ServerContextProvider` interface.

The default provider is disabled and never affects ticket creation. The optional HTTP provider requests:

```text
GET {base_url}/v1/server-context/{server_key}
Authorization: Bearer {authentication_token}
```

Example response:

```json
{
  "proxy_status": "online",
  "upstream_status": "online",
  "bds_version": "26.44",
  "protocol_version": 900,
  "server_name": "The Kingdom",
  "uptime_seconds": 18422,
  "player_count": 17,
  "tps": 20.0,
  "tick_health": "healthy",
  "recent_restart": false,
  "resource_pack_revision": "packs-2026-08-20.1",
  "addon_revision": "addons-85c1a8d",
  "transfer_route": "hub -> kingdom",
  "warning_summary": "No matching warnings"
}
```

Only documented fields are retained. HTTP errors, timeouts, invalid JSON, or an unavailable endpoint add a non-blocking snapshot error and do not reject the report.

The endpoint is intentionally an adapter contract rather than an invented OniLink implementation. Connect it to the actual control-plane route when that API exists.

## Security and privacy

- Tokens and configured authentication secrets are redacted from logs.
- `AllowedMentions.none()` is the default for user-controlled content.
- Staff and reporter pings are enabled only for intentional messages.
- Channel names are ASCII-normalized and sanitized.
- File paths are resolved and checked against their configured root.
- Uploaded evidence is not executed or extracted.
- Ticket channels deny `View Channel` to `@everyone`.
- The bot does not request Administrator.
- Ticket King resources remain outside this bot's managed scope.
- Internal known-issue notes are never displayed in the public known-issues panel.

## Troubleshooting

### Slash commands do not appear

- Confirm the invite included `applications.commands`.
- Set `KTD_DEV_GUILD_ID` during testing for immediate guild sync.
- Check startup logs for the command-sync count.
- Global command changes can take longer to appear than guild commands.

### Panel buttons say interaction failed

- Confirm the bot is running.
- Run `/tech panel refresh`.
- Run `/tech repair` and check that persistent views are registered.
- Confirm the bot can view and send messages in the panel channel.

### Ticket passes validation but no channel is created

- Run `/tech repair`.
- Confirm the open category exists.
- Confirm Manage Channels and Manage Roles.
- Confirm the bot role is high enough to create the required overwrites.
- A failed channel creation is retained as `CREATION_FAILED`; Resume Draft retries the same ticket number.

### Transcripts have empty message content

Enable Message Content intent in the Developer Portal and restart the bot.

### Evidence does not copy

- Check the file extension and actual file format.
- Check the automatic evidence limit.
- Check disk space and permissions for `data/evidence/`.
- Oversized files should be uploaded directly in the accepted ticket.

### Database is locked

The bot uses WAL mode, a busy timeout, and a process-local transaction lock. Do not run multiple bot processes against the same SQLite file.

## Development and tests

Install development dependencies:

```bash
python -m pip install -r requirements-dev.txt
```

Run tests:

```bash
pytest -q
```

Compile every module:

```bash
python -m compileall -q kingdom_tech_desk
```

Run Ruff when installed:

```bash
ruff check .
ruff format --check .
```

## Project layout

```text
kingdom_tech_desk/
  bot.py
  commands/
  database/
  intake/
  models/
  services/
  templates/
  tickets/
pterodactyl/
scripts/
tests/
```

## License

MIT. See `LICENSE`.
