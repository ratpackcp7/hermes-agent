# ~/.hermes/cron/ — Cron Job Documentation

## How the Cron System Works

The Hermes cron system is built into the gateway process. The gateway's cron scheduler (`cron/scheduler.py`) reads `jobs.json`, evaluates schedules, and spawns agent sessions to execute jobs.

**Key file:** `~/.hermes/cron/jobs.json`
**Runner:** `hermes-gateway.service` (in-process scheduler, NOT systemd timers)
**Schedule format:** Standard 5-field cron (`0 1 * * *` = daily at 1:00 AM)
**Delivery:** Results sent to the `deliver` target (Telegram, Discord, etc.)

The scheduler:
1. Loads `jobs.json` at gateway startup
2. Evaluates `schedule.expr` cron expressions against current time
3. At the scheduled time, spawns a fresh agent session with the job's prompt
4. If `skills` are specified, loads them before executing the prompt
5. If `script` is specified, runs the pre-script and injects stdout as context
6. The agent's final response is delivered to the `deliver` target
7. `repeat.times` controls how many times a job runs (null = forever)

## Active Jobs

### nightly-retrospective
- **Schedule:** `0 1 * * *` (daily at 1:00 AM CT)
- **Model:** claude-sonnet-4 (anthropic)
- **Skills:** nightly-retrospective
- **Delivers to:** Telegram (Chris)
- **What it does:** Gathers prior day's git commits, sessions, gateway errors, service crashes. Writes a structured retrospective, persists lessons to Honcho, grades process discipline. Outputs to `~/.hermes/retro/YYYY-MM-DD.md`.
- **Runs:** 20 completed (as of 2026-04-12)
- **Next run:** 2026-04-13 01:00 CT

### homelab-health
- **Schedule:** `0 8 * * *` (daily at 8:00 AM CT)
- **Model:** claude-sonnet-4 (anthropic)
- **Skills:** none
- **Delivers to:** Telegram (Chris)
- **What it does:** Checks disk usage, memory, CPU load, Docker container status, failed systemd services, restic backup status, uptime. Sends concise health report.
- **Runs:** 20 completed
- **Next run:** 2026-04-13 08:00 CT

### Weekly Finance Report
- **Schedule:** `0 8 * * 0` (Sundays at 8:00 AM CT)
- **Model:** claude-sonnet-4 (anthropic)
- **Skills:** none
- **Delivers to:** Telegram (Chris)
- **What it does:** Queries finance-hub PostgreSQL, generates self-contained HTML report with Chart.js (dark theme, sharp corners). Sections: summary cards, monthly income/expense bars, category breakdown, doughnut chart, heatmap, merchant table, recurring expenses.
- **Runs:** 3 completed
- **Next run:** 2026-04-19 08:00 CT

### Insurance spending monitor
- **Schedule:** `0 9 * * 1` (Mondays at 9:00 AM CT)
- **Model:** claude-sonnet-4 (anthropic)
- **Skills:** empower-monthly-audit
- **Delivers to:** Telegram (Chris)
- **What it does:** Queries Empower SQLite for insurance transactions in the last 30 days. Compares against known recurring patterns (NY Life, Northwestern Mutual, Allstate, AAA). Flags unexpected merchants, amount deviations, cancelled-policy charges, or bare "insurance" category.
- **Runs:** 2 completed
- **Next run:** 2026-04-13 09:00 CT

### Blogwatcher daily digest
- **Schedule:** `0 7 * * *` (daily at 7:00 AM CT)
- **Model:** xiaomi/mimo-v2-pro (nous)
- **Skills:** none
- **Pre-script:** `blogwatcher-digest.py`
- **Delivers to:** Telegram (Chris)
- **What it does:** Runs blogwatcher digest script, then curates top 3-5 posts worth reading (ranked by signal for Chris's stack), groups the rest by blog. Responds `[SILENT]` if no new posts.
- **Runs:** 6 completed
- **Next run:** 2026-04-13 07:00 CT

### wiki-ingest
- **Schedule:** `30 7 * * *` (daily at 7:30 AM CT)
- **Model:** default (inherits from config)
- **Skills:** llm-wiki
- **Pre-script:** `wiki-ingest-prep.py`
- **Delivers to:** Telegram (Chris)
- **What it does:** Ingests blogwatcher articles into the wiki. Step 1: capture verbatim to `raw/blogs/`. Step 2: selectively compile to `engineering/` using P8 Context7 filter (only compile what Context7 can't answer). Step 3: report.
- **Runs:** 0 completed (newly created 2026-04-11)
- **Next run:** null (has not run yet)

### wiki-monthly-prune
- **Schedule:** `0 9 1 * *` (1st of month at 9:00 AM CT)
- **Model:** default (inherits from config)
- **Skills:** llm-wiki
- **Delivers to:** Telegram (Chris)
- **What it does:** Reviews all compiled wiki pages. Trims "Recent changes" to 90 days, consolidates noisy entries, checks `last_verified` freshness by churn rate, removes unused source entries, flags pages over 200 lines for splitting.
- **Runs:** 0 completed (newly created 2026-04-11)
- **Next run:** null (has not run yet)

## Job Configuration Fields

| Field | Purpose |
|-------|---------|
| `id` | Unique hex identifier |
| `name` | Human-readable name |
| `prompt` | Full self-contained prompt for the agent session |
| `skills` | Array of skill names to load before execution |
| `model` | Model override (null = use default from config.yaml) |
| `provider` | Provider override |
| `schedule.kind` | Schedule type (`cron` or `interval`) |
| `schedule.expr` | Cron expression (`0 1 * * *`) |
| `repeat.times` | Max runs (null = forever) |
| `repeat.completed` | Count of completed runs |
| `enabled` | Whether the job is active |
| `state` | Current state (`scheduled`, `running`) |
| `paused_at` | Timestamp if paused |
| `deliver` | Delivery target (`telegram`, `discord`, etc.) |
| `origin` | Platform origin (chat_id, channel info) |
| `script` | Pre-script path (relative to `~/.hermes/scripts/`) |
| `last_run_at` | Last execution timestamp |
| `last_status` | Last run status (`ok`, `error`) |
| `last_error` | Error message if failed |

## Managing Jobs

### List jobs
The cron tool in any agent session: `cronjob(action='list')`

### Add a job
```json
{
  "action": "create",
  "name": "my-job",
  "prompt": "Do the thing...",
  "schedule": "0 9 * * *",
  "deliver": "telegram",
  "model": {"model": "claude-sonnet-4", "provider": "anthropic"},
  "skills": ["skill-name"],
  "script": "optional-pre-script.py"
}
```

### Pause/resume
```json
{"action": "pause", "job_id": "abc123"}
{"action": "resume", "job_id": "abc123"}
```

### Update
```json
{"action": "update", "job_id": "abc123", "schedule": "0 10 * * *"}
```

### Remove
```json
{"action": "remove", "job_id": "abc123"}
```

### Manual trigger
```json
{"action": "run", "job_id": "abc123"}
```

## Error Handling

- If a job fails, `last_error` is set and `last_status` shows the error
- Failed jobs DO NOT retry automatically — they wait for the next scheduled run
- The scheduler itself runs inside `hermes-gateway.service` — if the gateway restarts, all jobs reschedule from their cron expressions
- Jobs that time out (agent exceeds `gateway_timeout`) are marked as failed
- The `cron.wrap_response: true` config setting wraps the agent response before delivery

## Important Notes

- **Jobs run in isolation** — no conversation context from prior runs or other sessions
- **Prompts must be self-contained** — include all context, file paths, and instructions
- **Jobs should not schedule other cron jobs** — recursive scheduling is prohibited
- **`[SILENT]` response** — if the agent responds with exactly `[SILENT]`, nothing is delivered
- **Pre-scripts** run before the agent session starts; stdout is injected as context into the prompt
- **Model pinning** — if `model` is set at creation time, the provider is pinned so the job stays stable even if the main config changes
