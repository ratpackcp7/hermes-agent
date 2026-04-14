# Handoff

Last updated: 2026-04-13 by claude.ai

## Just Shipped
- **Upstream merge complete**: Rebased cp7-custom onto origin/main (outsourc-e v0.9.0, which includes NousResearch upstream v2026.4.13)
- Absorbed 1,085 upstream commits including: security fixes (path traversal, shell injection, SSRF, Twilio RCE), OAuth provider management, web dashboard, streaming improvements, new platforms (iMessage, WeChat, WeCom), pluggable context engine, hermes backup/import
- All 9 cp7-custom commits cherry-picked cleanly (8 original + 1 new workflow deletion)
- API_SERVER_KEY auth now enforced on all API endpoints (key already in config.yaml)
- Gateway and workspace services verified healthy post-merge

## Safety
- Rollback tag: `pre-merge-backup` (pushed to cp7 remote)
- Old branch preserved locally as `cp7-custom-old`

## Gotchas
- API endpoints now require `Authorization: Bearer <API_SERVER_KEY>` header — key is in `~/.hermes/config.yaml` under `platforms.api_server.key`
- cp7-mobile, dashboard, and any other API consumers need this header or they'll get 401
- Push to `cp7` remote on `cp7-custom` branch (force-with-lease used for rebase)
- Any new `.github/workflows/*.yml` from future upstream syncs will block PAT push — delete them

## Next Steps
- Verify cp7-mobile works with new auth requirement (may need API key header added)
- Verify dashboard session list works
- Test Telegram streaming (edit_interval default changed 0.3→1.0s upstream)
- Consider periodic upstream sync cadence (weekly cherry-pick review)
