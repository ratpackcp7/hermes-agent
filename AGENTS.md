# Hermes Agent — CP7 Outsource Fork

## Purpose

Hermes Agent is a self-improving AI agent built by Nous Research, forked and maintained locally at `/home/chris/projects/hermes-agent-outsource/`. It features a closed learning loop (skill creation from experience, autonomous improvement), persistent memory with FTS5 search, multi-platform messaging gateway, scheduled cron automations, and 40+ tools including terminal backends, web search, browser automation, and MCP integration.

This CP7 fork tracks upstream `outsourc-e` releases (currently v0.9.0) with custom patches applied on the `cp7-custom` branch. It is deployed as a local Python package (not a Docker container) and serves as the primary agent runtime for acerserver.

## Key Facts

- **Ports**: WebAPI defaults to `127.0.0.1:8642` (falls back to 8643 if busy); API Server (OpenAI-compatible) defaults to `127.0.0.1:8642`
- **URL**: No public tunnel — local-only via `127.0.0.1:8642`
- **Stack**: Python 3.11+, FastAPI (webapi), aiohttp (gateway platforms), SQLite (session store), uv (dependency management), Node.js (Playwright + WhatsApp bridge)
- **Deploy**: Local Python package installed in a venv at repo root; entry points `hermes` (CLI) and `hermes gateway` (messaging gateway). Dockerfile exists for containerized deployments but is not used on acerserver.
- **Health Check**: `curl http://127.0.0.1:8642/health` → `{"status": "ok", "platform": "hermes-agent", "service": "webapi"}`
- **Config**: `~/.hermes/config.yaml` (settings), `~/.hermes/.env` (API keys), `~/.hermes/SOUL.md` (persona)
- **Repo**: `https://github.com/NousResearch/hermes-agent.git` (upstream); local remote `cp7` tracks `cp7-custom` branch
- **Branch**: `cp7-custom` (rebased onto upstream v0.9.0)

## Architecture

```
run_agent.py              # AIAgent class — core conversation loop
cli.py                    # HermesCLI — interactive terminal UI
model_tools.py            # Tool orchestration, discovery, dispatch
toolsets.py               # Toolset definitions and enable/disable logic
hermes_state.py           # SessionDB — SQLite with FTS5 search

agent/                    # Agent internals
  prompt_builder.py       # System prompt assembly
  context_compressor.py   # Auto context compression
  prompt_caching.py       # Anthropic prompt caching
  auxiliary_client.py     # Auxiliary LLM client
  display.py              # KawaiiSpinner, tool preview formatting
  skill_commands.py       # Slash command handlers for skills
  trajectory.py           # Trajectory saving helpers

hermes_cli/               # CLI subcommands and setup
  main.py                 # Entry point for all `hermes` subcommands
  config.py               # DEFAULT_CONFIG, OPTIONAL_ENV_VARS, migration
  commands.py             # Central slash command registry
  setup.py                # Interactive setup wizard

 tools/                   # Tool implementations (one file per tool)
  registry.py             # Central tool registry
  file_tools.py           # File read/write/search/patch
  web_tools.py            # Web search/extract
  browser_tool.py         # Browser automation
  terminal_tool.py        # Terminal orchestration
  environments/           # Terminal backends (local, docker, ssh, modal, daytona, singularity)

gateway/                  # Messaging platform gateway
  run.py                  # Main event loop, slash commands, dispatch
  session.py              # SessionStore — conversation persistence
  platforms/              # Adapters: telegram, discord, slack, whatsapp, signal, etc.
  platforms/api_server.py # OpenAI-compatible API server

webapi/                   # FastAPI REST API
  app.py                  # FastAPI app with CORS middleware
  routes/                 # chat, sessions, skills, memory, models, config, health

cron/                     # Built-in scheduler
  jobs.py                 # Job CRUD, schedule parsing
  scheduler.py            # tick() — checks and runs due jobs

acp_adapter/              # ACP server (VS Code / Zed / JetBrains IDE integration)
plugins/                  # Pluggable memory backends (honcho, mem0, supermemory, etc.)
tests/                    # Pytest suite (~7,500 tests)
```

**Data flow**: User message → gateway/run.py or cli.py → AIAgent.run_conversation() → model_tools.py dispatches tool calls → tools/*.py execute → results appended to messages → loop until final response.

**File dependency chain**: `tools/registry.py` (no deps) → `tools/*.py` (register at import) → `model_tools.py` (triggers discovery) → `run_agent.py`, `cli.py`, `gateway/run.py`, `batch_runner.py`.

## Agents and Crons

- **Built-in cron scheduler** (`cron/scheduler.py`): The gateway calls `tick()` every 60 seconds from a background thread to check for due jobs and execute them. Jobs are stored in `~/.hermes/cron/jobs.json`. No external cron or systemd timer is used.
- No other external agents or crons touch this project.

## Gotchas

- **Hardcoding `~/.hermes` breaks profiles**: Always use `get_hermes_home()` from `hermes_constants` for code paths, and `display_hermes_home()` for user-facing messages. Each profile has its own isolated `HERMES_HOME` directory.
- **DO NOT use `simple_term_menu`**: Rendering bugs in tmux/iTerm2 cause ghosting on scroll. Use `curses` (stdlib) instead.
- **DO NOT use `\033[K` (ANSI erase-to-EOL) in spinner/display code**: Leaks as literal `?[K` text under `prompt_toolkit`'s `patch_stdout`. Use space-padding: `f"\r{line}{' ' * pad}"`.
- **API endpoints now require `Authorization: Bearer <API_SERVER_KEY>`**: Post-v0.9.0 merge, all API endpoints enforce this header. Key lives in `~/.hermes/config.yaml` under `platforms.api_server.key`. Any client (cp7-mobile, dashboard, etc.) must include this header or gets 401.
- **Prompt caching must not break**: Never alter past context mid-conversation, change toolsets mid-conversation, or reload memories/rebuild system prompts mid-conversation. Cache-breaking forces dramatically higher costs.
- **`_last_resolved_tool_names` is a process-global in `model_tools.py`**: Subagent delegation saves/restores this global. Code reading it may see temporarily stale values during child agent runs.
- **Tests must not write to `~/.hermes/`**: The `_isolate_hermes_home` autouse fixture in `tests/conftest.py` redirects `HERMES_HOME` to a temp dir.
- **Future upstream `.github/workflows/*.yml` files will block PAT push**: Delete them before pushing to the `cp7` remote.

## Active Work

See HANDOFF.md.

## Decisions

See `docs/decisions/`. No ADRs exist yet.

<!-- CP7-AGENT-STANDARDS:START -->

## CP7 Agent Standard

Before behavior changes, read `/home/chris/cp7-bridge/docs/agent-standards/AGENT-OPERATING-STANDARD.md`, this project's README/HANDOFF, and `docs/decisions/`.

Create or update an ADR for changes to ports, bind addresses, tunnels, Docker Compose, volumes, healthchecks, systemd, timers, persistent data paths, MCP tools, auth, allowlists, writable roots, or unusual config.

Every change report must include what changed, why, verification, rollback, and touched files/services.

Verifier:

```bash
/home/chris/cp7-bridge/scripts/verify_agent_standards.sh /home/chris/projects/hermes-agent-outsource
```

<!-- CP7-AGENT-STANDARDS:END -->
