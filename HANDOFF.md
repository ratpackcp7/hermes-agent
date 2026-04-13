# Handoff

Last updated: 2026-04-13 by claude.ai

## Just Shipped
- Upstream CI workflows removed (not needed for local deployment)
- Skills count verified: 153 skills, ~7,500 tests

## In Flight
- Nothing actively in progress — Bob runs on this via systemd user services

## Gotchas
- Upstream fork: push to `cp7` remote on `cp7-custom` branch
- This is the agent runtime — hermes-gateway.service runs from this codebase

## Next Steps
- Pull upstream updates as new Hermes releases land
- Audit skills periodically (some may go stale)
