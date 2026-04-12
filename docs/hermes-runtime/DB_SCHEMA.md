# ~/.hermes/ Database Schema Reference

Complete schema documentation for all SQLite databases in the Hermes runtime directory.

## state.db — Primary Data Store

**Path:** `~/.hermes/state.db`
**Size:** ~109MB (including WAL)
**Mode:** WAL (write-ahead logging)
**Written by:** hermes-gateway process (primary), CLI sessions (secondary)

### Tables

#### sessions
One row per conversation session. This is the authoritative session store.

```sql
CREATE TABLE sessions (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL,              -- "telegram", "discord", "cli", "claude-supervisor", "cron", "api"
    user_id TEXT,
    model TEXT,
    model_config TEXT,
    system_prompt TEXT,
    parent_session_id TEXT,            -- FK to sessions.id (supervisor → child dispatch)
    started_at REAL NOT NULL,          -- Unix epoch float
    ended_at REAL,
    end_reason TEXT,
    message_count INTEGER DEFAULT 0,
    tool_call_count INTEGER DEFAULT 0,
    input_tokens INTEGER DEFAULT 0,
    output_tokens INTEGER DEFAULT 0,
    cache_read_tokens INTEGER DEFAULT 0,
    cache_write_tokens INTEGER DEFAULT 0,
    reasoning_tokens INTEGER DEFAULT 0,
    billing_provider TEXT,
    billing_base_url TEXT,
    billing_mode TEXT,
    estimated_cost_usd REAL,
    actual_cost_usd REAL,
    cost_status TEXT,
    cost_source TEXT,
    pricing_version TEXT,
    title TEXT,                        -- Session title (unique where not null)
    FOREIGN KEY (parent_session_id) REFERENCES sessions(id)
);
```

**Indexes:**
- `idx_sessions_source` ON `source`
- `idx_sessions_parent` ON `parent_session_id`
- `idx_sessions_started` ON `started_at DESC`
- `idx_sessions_title_unique` UNIQUE on `title WHERE title IS NOT NULL`

**Row count:** 933 sessions (as of 2026-04-12)

**Key columns for queries:**
- `source` — filter by platform (telegram, discord, cli, cron, claude-supervisor)
- `started_at` — unix epoch; use for date range queries
- `parent_session_id` — links supervisor dispatches to child sessions
- `message_count`, `tool_call_count` — activity metrics
- `estimated_cost_usd`, `actual_cost_usd` — billing tracking

**Common queries:**
```sql
-- Sessions from prior day (for retrospectives)
SELECT source, COUNT(*), SUM(message_count), SUM(tool_call_count)
FROM sessions
WHERE started_at >= ? AND started_at < ?
GROUP BY source;

-- Supervisor-dispatched sessions
SELECT * FROM sessions WHERE parent_session_id IS NOT NULL ORDER BY started_at DESC LIMIT 20;

-- Token usage by day
SELECT date(started_at, 'unixepoch', 'localtime') as day,
       SUM(input_tokens), SUM(output_tokens), SUM(estimated_cost_usd)
FROM sessions GROUP BY day ORDER BY day DESC LIMIT 7;
```

#### messages
Every message in every conversation — user, assistant, and tool messages.

```sql
CREATE TABLE messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES sessions(id),
    role TEXT NOT NULL,                -- "user", "assistant", "tool", "system"
    content TEXT,
    tool_call_id TEXT,
    tool_calls TEXT,
    tool_name TEXT,
    timestamp REAL NOT NULL,           -- Unix epoch float
    token_count INTEGER,
    finish_reason TEXT,
    reasoning TEXT,                    -- Chain-of-thought reasoning (assistant only)
    reasoning_details TEXT,
    codex_reasoning_items TEXT
);
```

**Indexes:**
- `idx_messages_session` ON `(session_id, timestamp)`

**Row count:** 32,979 messages

**FTS5 full-text search index** (auto-synced via triggers):
```sql
CREATE VIRTUAL TABLE messages_fts USING fts5(content, content=messages, content_rowid=id);
```
Triggers handle insert/delete/update automatically. Search via:
```sql
SELECT m.* FROM messages m JOIN messages_fts fts ON m.id = fts.rowid
WHERE messages_fts MATCH 'search terms' ORDER BY rank LIMIT 10;
```

#### schema_version
Tracks database schema version for migrations.
```sql
CREATE TABLE schema_version (version INTEGER NOT NULL);
```

### What's Important to Back Up

| Data | Critical? | Why |
|------|-----------|-----|
| `sessions` table | **YES** | Session metadata, costs, parent-child dispatch links |
| `messages` table | **YES** | Full conversation history — the primary value |
| `messages_fts` | No | Rebuilt automatically from messages |
| `schema_version` | No | Single row, trivial to recreate |

`state.db` is backed up nightly via Restic. The session JSONL files in `sessions/` are a secondary copy of message content.

---

## sessions.db — Session Index (Legacy)

**Path:** `~/.hermes/sessions.db`
**Size:** 4KB
**Written by:** Gateway session store
**Status:** Effectively empty — state.db is authoritative.

Contains a single empty `sessions` table. This file exists from an earlier architecture where it was the primary session store. It has been superseded by `state.db`. Safe to ignore.

---

## response_store.db — Response Cache

**Path:** `~/.hermes/response_store.db`
**Size:** 20KB
**Written by:** Gateway
**Status:** Empty (0 rows in both tables)

### Tables

#### responses
```sql
CREATE TABLE responses (
    response_id TEXT PRIMARY KEY,
    data TEXT NOT NULL,
    accessed_at REAL NOT NULL
);
```

#### conversations
```sql
CREATE TABLE conversations (
    name TEXT PRIMARY KEY,
    response_id TEXT NOT NULL
);
```

Purpose: Cache intermediate responses for cross-turn reference. Currently unused. Safe to recreate.

---

## workspace.db — Workspace State

**Path:** `~/.hermes/workspace.db`
**Size:** 0 bytes
**Status:** Unused/empty. No tables.

---

## Cross-Database Relationships

There are no foreign key relationships across database files. Each is independent:
- `state.db` is self-contained (sessions + messages)
- `response_store.db` references response IDs internally
- `workspace.db` is empty

## Backup Priority

| Priority | Database | Reason |
|----------|----------|--------|
| **1 (critical)** | `state.db` | All session data, conversation history, cost tracking |
| 2 (low) | `response_store.db` | Currently empty, ephemeral cache |
| 3 (none) | `sessions.db` | Legacy, empty |
| 3 (none) | `workspace.db` | Empty |

Also back up:
- `sessions/` directory (1,811 JSONL conversation transcripts)
- `memories/MEMORY.md` and `memories/USER.md` (L1 context)
- `config.yaml` (rebuildable but painful to reconstruct)

The `cron/jobs.json` file is also worth backing up (7 active cron jobs).

## Ephemeral vs Persistent

| File | Ephemeral? | Notes |
|------|-----------|-------|
| `state.db` | **No** | Primary data — never delete |
| `state.db-wal` | **No** | WAL segment — part of state.db |
| `state.db-shm` | Yes | Shared memory header — rebuilt on restart |
| `sessions/` | **No** | Conversation transcripts |
| `response_store.db` | Yes | Currently empty |
| `sessions.db` | Yes | Legacy, empty |
| `workspace.db` | Yes | Empty |
| `gateway.pid` | Yes | Recreated on gateway start |
| `gateway_state.json` | Yes | Recreated on gateway start |
| `processes.json` | Yes | Background process registry |
| `models_dev_cache.json` | Semi | Can be re-fetched but is 1.7MB — back up to avoid API hits |
| `checkpoints/` | Semi | Useful for recovery but not critical |
| `logs/` | Yes | Rotated automatically |
