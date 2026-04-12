# CLAUDE.md — Hermes Agent

Bob's backend agent runtime. Nous Research Hermes Agent, forked by outsourc-e.

## Before You Start
- **`AGENTS.md`** — full architecture doc (project structure, dependency chain, adding tools/commands, testing). Read it first.
- **`~/.hermes/SOUL.md`** — Bob's operating instructions (CLAUDE.md protocol, self-preservation, delegation rules, debugging protocol)
- **`docs/`** — migration guides, skin examples, ACP setup, Honcho integration spec, pricing architecture

## Key Facts
- **Port**: 8642 | **Health**: `curl http://127.0.0.1:8642/health` → `{"status":"ok","platform":"hermes-agent"}`
- **Deploy**: systemd user service `hermes-gateway.service` — `python -m hermes_cli.main gateway run --replace`
- **Logs**: `~/.hermes/logs/gateway.log`, `~/.hermes/logs/errors.log`, `~/.hermes/logs/agent.log`
- **Restart**: `~/.hermes/scripts/safe-restart-gateway.sh` (NOT `systemctl restart` — kills Bob's process)
- **Config**: `~/.hermes/config.yaml` (settings), `~/.hermes/.env` (API keys)
- **State**: `~/.hermes/state.db`, `~/.hermes/sessions.db`

## Architecture
```
Telegram/Discord/CLI/Workspace (port 3002)
        ↓ HTTP
  Gateway (port 8642)  ← this repo
        ├── run.py — message dispatch, slash commands, platform adapters
        ├── session.py — SessionStore (conversation persistence)
        ├── platforms/ — 19 adapters (telegram, discord, slack, whatsapp, homeassistant, signal, etc.)
        └── AIAgent (run_agent.py) — core conversation loop
                ├── model_tools.py — tool orchestration, _discover_tools()
                ├── tools/registry.py — central tool registry
                └── tools/*.py — terminal, file, web, browser, delegate, MCP, code execution
```
- **Auth flow**: HMAC-signed tokens. Gateway validates webhook signatures per platform. Home Assistant uses `HASS_TOKEN`. DM pairing for unauthorized users.
- **Honcho session isolation**: session keys are `api_server:{session_id}` — each gateway session gets its own Honcho context.
- All platforms (Telegram, Workspace, CLI) hit port 8642 — it's the single entry point.

## Operational Procedures
- **Safe restart**: `~/.hermes/scripts/safe-restart-gateway.sh` — notifies Chris via Telegram before/after, polls `/health` up to 30s. NEVER use `systemctl --user restart hermes-gateway` directly (kills Bob's context, conversation lost).
- **Health check**: `curl http://127.0.0.1:8642/health`
- **Read logs**: `tail -50 ~/.hermes/logs/gateway.log | grep -i <platform>` and `tail -50 ~/.hermes/logs/errors.log`
- **Watchdog**: checks every 5 minutes, auto-restarts gateway if dead and script didn't bring it back.
- **Lock cleanup**: empty `.lock` files at `~/.local/state/hermes/gateway-locks/` block token acquire post-crash — `rm` them.

## Dependencies
- **Honcho**: port 8000 (session memory, context engine)
- **Hermes Workspace**: port 3002 (bob.cp7.dev — web UI)
- **Telegram Bot Token**: in `~/.hermes/.env` (`TELEGRAM_BOT_TOKEN`)

## Known Pitfalls
- **Restarting kills Bob** — `hermes-gateway.service` restart terminates the running agent process. Always use `safe-restart-gateway.sh`.
- **HMAC token flow** — don't modify auth without understanding self-verifying token generation in the workspace.
- **Don't hardcode `~/.hermes`** — use `get_hermes_home()` from `hermes_constants.py` (supports profiles).
- **Python venv required** — `source venv/bin/activate` before running any Python commands.
- **Test suite**: `python -m pytest tests/ -q` (~3000 tests, ~3 min). Run full suite before pushing changes.
