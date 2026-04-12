# ~/.hermes/ — Hermes Agent Runtime Directory

Runtime data directory for the Hermes AI agent system. This is **not** the code — it's where config, state, logs, skills, and session data live at runtime.

## Directory Layout

```
~/.hermes/
├── config.yaml              # Main config (model, toolsets, display, platform settings)
├── .env                     # API keys and secrets (TELEGRAM_BOT_TOKEN, OPENROUTER_API_KEY, etc.)
├── SOUL.md                  # Agent personality/rules injected into every session
├── auth.json                # OAuth tokens for providers (Nous, Anthropic, etc.)
├── gateway.pid              # PID file for running gateway process
├── gateway_state.json       # Gateway runtime state: platform connection status, errors
├── channel_directory.json   # Known messaging channels (Telegram, Discord) with IDs
├── processes.json           # Background process registry
├── models_dev_cache.json    # Cached model registry from models.dev (~1.7MB)
│
├── hermes-agent/            # SYMLINK to ~/projects/hermes-agent-outsource (the code)
│
├── sessions/                # 1,811 JSONL files — one per conversation session
├── sessions.db              # Lightweight session index (mostly empty, superseded by state.db)
├── state.db                 # PRIMARY DATABASE (109MB) — sessions, messages, FTS search
├── response_store.db        # Response cache (20KB, currently empty)
├── workspace.db             # Workspace state (0 bytes, currently unused)
│
├── skills/                  # 31 category dirs, 153 skill definitions (SKILL.md + files)
├── memories/                # L1 memory: MEMORY.md (injected every turn), USER.md (user profile)
├── logs/                    # agent.log, gateway.log, errors.log, watchdog.log
├── cron/                    # jobs.json — scheduled cron job definitions
├── checkpoints/             # 19 conversation checkpoint snapshots
├── retro/                   # Nightly retrospective output files
├── hooks/                   # Activity tracker hooks
├── scripts/                 # Operational scripts (safe restart, blogwatcher, wiki tools)
├── rules/                   # Agent rule files (build-discipline.md, etc.)
├── plans/                   # Saved execution plans
├── sandboxes/               # Sandbox environments
├── browser_screenshots/     # Browser automation screenshots
├── image_cache/             # Generated image cache
├── images/                  # Image storage
├── audio_cache/             # TTS audio cache
├── document_cache/          # Document extraction cache
├── pastes/                  # Paste storage
├── pairing/                 # Device pairing data
├── fork-patches/            # Saved patches for upstream fork
├── hub-data/                # Hub/dashboard data
├── whatsapp/                # WhatsApp platform data
├── knowledge -> /home/chris/wiki  # SYMLINK to wiki knowledge base
│
├── .hermes_history          # CLI command history
├── .skills_prompt_snapshot.json  # Cached skills prompt for injection
├── .envsk-or-v1-...         # Stray credential file (should be cleaned)
└── .update_check            # Last update check timestamp
```

## How the Gateway Uses This Directory

`hermes-gateway.service` runs with `HERMES_HOME=/home/chris/.hermes`. The gateway process:

1. **Reads** `config.yaml` + `.env` at startup for model, platform, and tool configuration
2. **Reads** `SOUL.md` to inject agent personality into every conversation
3. **Reads** `auth.json` for OAuth provider tokens
4. **Writes** to `state.db` — session records, messages, token counts, costs
5. **Writes** session JSONL files to `sessions/` — full conversation transcripts
6. **Writes** `gateway_state.json` with platform connection status
7. **Writes** logs to `logs/gateway.log`, `logs/agent.log`, `logs/errors.log`
8. **Reads** `skills/` at startup to build available skill list
9. **Reads** `memories/MEMORY.md` + `memories/USER.md` for cross-session context
10. **Reads/writes** `cron/jobs.json` for scheduled job definitions
11. **Reads** `channel_directory.json` to route messages to correct platforms

The systemd unit:
```
ExecStart=/home/chris/.hermes/hermes-agent/venv/bin/python -m hermes_cli.main gateway run --replace
WorkingDirectory=/home/chris/.hermes/hermes-agent
Environment="HERMES_HOME=/home/chris/.hermes"
```

## Config Files

### config.yaml — Main Configuration

Key sections:
- **`model`** — default model and provider (currently `xiaomi/mimo-v2-pro` on `nous`)
- **`fallback_providers`** — ordered failover list when primary is unavailable
- **`agent`** — max_turns (60), gateway_timeout (1800s), personalities (bob, concise, etc.), reasoning_effort
- **`terminal`** — backend (local), timeout (180s), Docker sandbox settings
- **`browser`** — inactivity_timeout (120s), command_timeout (30s)
- **`compression`** — auto context compression (threshold 0.7, target 0.25 ratio, protects last 30 messages)
- **`auxiliary`** — separate model configs for vision, web_extract, compression, session_search, approval, MCP
- **`display`** — personality, skin, streaming, token usage display, tool progress
- **`memory`** — honcho provider, char limits (MEMORY: 2200, USER: 1375), flush_min_turns: 6
- **`delegation`** — subagent model/provider, default toolsets (terminal, file, web)
- **`skills`** — external_dirs, creation_nudge_interval
- **`gateway`** — platform enable/disable (telegram, discord), allowed_users
- **`platform_toolsets`** — which tools are available per platform (cli, telegram, discord, etc.)
- **`cron`** — wrap_response: true
- **`logging`** — level INFO, max 5MB × 3 rotated files
- **`security`** — tirith command scanning, redact_secrets, website_blocklist
- **`session_reset`** — auto-reset at 4AM or after 8h idle
- **`mcp_servers`** — external MCP server configs (context7)

### .env — Secrets and API Keys

Environment variables (names only, never values):
| Variable | Purpose |
|----------|---------|
| `TELEGRAM_BOT_TOKEN` | Telegram bot authentication |
| `DISCORD_BOT_TOKEN` | Discord bot authentication |
| `DISCORD_REQUIRE_MENTION` | Whether Discord needs @mention to trigger |
| `DISCORD_ALLOWED_USERS` | Discord user IDs allowed to interact |
| `OPENROUTER_API_KEY` | OpenRouter provider API key |
| `ANTHROPIC_TOKEN` | Anthropic provider API key |
| `HERMES_MAX_ITERATIONS` | Override max agent iterations (60) |
| `HERMES_AGENT_TIMEOUT` | Agent conversation timeout (900s) |
| `FAL_KEY` | Fal.ai image generation API key |
| `FIRECRAWL_API_URL` | Firecrawl web extraction endpoint (local) |
| `API_SERVER_ENABLED` | Enable REST API server |
| `API_SERVER_KEY` | API server authentication key |
| `HASS_TOKEN` | Home Assistant long-lived token (commented out) |
| `HASS_URL` | Home Assistant URL (commented out) |

## Log Files

| File | What it captures | Size (typical) |
|------|-----------------|----------------|
| `logs/gateway.log` | Gateway process: platform connections, message routing, slash commands | ~4MB, rotated |
| `logs/agent.log` | Agent conversations: tool calls, API responses, errors | ~4MB |
| `logs/errors.log` | Error-level messages only (from both gateway and agent) | ~800KB |
| `logs/watchdog.log` | Watchdog health checks, restart events | ~120KB |
| `logs/gateway-restart.log` | Gateway restart history (from safe-restart-gateway.sh) | ~2KB |

**Reading logs:**
```bash
tail -50 ~/.hermes/logs/gateway.log | grep -i telegram   # Platform-specific debug
tail -50 ~/.hermes/logs/errors.log                        # Recent errors
grep "token_lock" ~/.hermes/logs/gateway.log              # Token conflict detection
journalctl --user -u hermes-gateway.service --since today  # Systemd journal (also available)
```

Log rotation: max 5MB per file, 3 backups (config.yaml `logging` section).

## Databases

See `DB_SCHEMA.md` for full schemas. Quick reference:

| Database | Purpose | Size | Key Tables |
|----------|---------|------|------------|
| `state.db` | Primary data store | ~109MB | `sessions` (933 rows), `messages` (32,979 rows) + FTS5 index |
| `sessions.db` | Session index | 4KB | Empty (state.db is authoritative) |
| `response_store.db` | Response cache | 20KB | `responses`, `conversations` (both empty) |
| `workspace.db` | Workspace state | 0 bytes | Unused |

## Scripts

| Script | Purpose |
|--------|---------|
| `scripts/safe-restart-gateway.sh` | **THE ONLY SAFE WAY** to restart the gateway. Notifies Chris via Telegram, restarts, polls health endpoint for 30s, confirms or alerts on failure. |
| `scripts/blogwatcher-digest.py` | Fetches RSS/Atom feeds, outputs new articles for the blogwatcher cron job |
| `scripts/blogwatcher-cache-feeds.py` | Pre-caches feed data for blogwatcher |
| `scripts/wiki-ingest-prep.py` | Prepares wiki ingest from blogwatcher output |
| `scripts/wiki-lint.py` | Lints wiki for staleness, broken links, missing frontmatter |
| `scripts/capture-source.sh` | Captures source code for review |
| `scripts/auto-reset-auth.sh` | Resets auth tokens |

## Runtime vs Code

| | `~/.hermes/` (this dir) | `~/projects/hermes-agent-outsource/` |
|---|---|---|
| **Purpose** | Runtime data | Source code |
| **Contains** | Config, state, logs, sessions, skills | Python source, tests, venv |
| **Modified by** | Gateway process, agent at runtime | Developer / cc-loop |
| **Backed up** | Yes (state.db matters) | Git-tracked |
| **Symlink** | `hermes-agent/` → code dir | — |

The `hermes-agent/` directory inside `~/.hermes/` is a **symlink** to `~/projects/hermes-agent-outsource/`. This is where the Python code and venv live. The gateway's `WorkingDirectory` points here.

## SOUL.md

`SOUL.md` contains the agent's core personality and operating rules. It's injected into every conversation as part of the system prompt. It defines:
- Rule #1: Always read CLAUDE.md before working on any repo
- Rule #2: Git is source of truth — commit all docs
- Style preferences (concise, direct, no fluff)
- Delegation strategy (Opus → Haiku/Sonnet subagents)
- Self-preservation (never restart gateway directly)
- cc-loop build delegation protocol

## Memories (L1/L2)

- `memories/MEMORY.md` — L1 memory, injected every turn. Char limit: 2,200. Contains environment facts, stable conventions, tool quirks.
- `memories/USER.md` — L1 user profile, injected every turn. Char limit: 1,375. Contains Chris's preferences, family details, work style.
- L2 memory is handled by Honcho (external service) for semantic search across sessions.

When L1 memory hits ~75% capacity, entries should be promoted to the wiki.

## Knowledge Base

`knowledge` is a symlink to `/home/chris/wiki/` — the three-layer knowledge base (raw → engineering → concepts). See `~/wiki/AGENTS.md` for the wiki protocol.
