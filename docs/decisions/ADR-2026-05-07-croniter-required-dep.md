# ADR-2026-05-07: Promote croniter to required dependency

## Status
Accepted

## Context
croniter was listed as an optional dependency under [project.optional-dependencies] cron.
It was never installed on acerserver. The scheduler compute_next_run() silently returns
None when HAS_CRONITER is False, causing all kind:cron jobs to have next_run_at=null and
never fire. Four cron jobs (cron-doc-drift-check, regen-acerserver-md, standards-audit,
bob-docs-drift-check) had never run as a result.

## Decision
Move croniter>=6.0.0,<7 from optional [cron] extras into core [project.dependencies].
Cron scheduling is a core gateway feature; making the parser optional silently breaks it
with no user-visible error.

## Consequences
- pip install -e . will always install croniter going forward
- The [cron] extra group remains for backwards compat but is now redundant
- All kind:cron jobs will have next_run_at computed correctly on first load
