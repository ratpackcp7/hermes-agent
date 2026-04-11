# CLAUDE.md — Hermes Agent (outsourc-e fork)

Bob's backend agent runtime. Nous Research Hermes Agent, forked by outsourc-e.

## Key Facts
- **Port**: 8642 (gateway)
- **Deploy**: systemd user service (`hermes-gateway.service`)
- Python project with Node components
- This is the ENGINE — hermes-workspace is the UI

## Important
- Do NOT modify without understanding the gateway ↔ workspace auth flow
- HMAC-signed tokens, Honcho session isolation (`api_server:{session_id}`)
- Bob's SOUL.md has self-preservation rules and debugging protocol
- Watchdog auto-restarts gateway on stale journal activity
