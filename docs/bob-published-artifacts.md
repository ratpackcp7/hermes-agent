# Bob Published Artifacts — Usage Guide

## Where artifacts are published

| Field | Value |
|-------|-------|
| Served root | `/home/chris/cp7-design` (nginx on port 8401) |
| URL base | `https://assets.cp7.dev` |
| Bob artifact directory | `/home/chris/cp7-design/bob/` |
| URL pattern | `https://assets.cp7.dev/bob/<filename>` |
| Access model | Cloudflare Zero Trust (Google OAuth + email OTP) for all `*.cp7.dev` routes |

Evidence for this mapping:

```
$ sudo cat /etc/nginx/sites-available/cp7-assets
server {
    listen 8401;
    server_name assets.cp7.dev localhost;
    root /home/chris/cp7-design;
    ...
}

$ bash /home/chris/cp7-bridge/scripts/cf-tunnel.sh list
assets.cp7.dev -> http://localhost:8401
```

## When to call `publish_artifact()`

Call it when Bob intentionally creates a file for Chris to view — for example:

- A generated report, changelog, or summary
- A diagnostic dump that's too long for a Telegram message
- A context handoff file that Chris needs to open
- A frozen-config snapshot or debug artifact

## When NOT to call it

Do **not** call it for:

- Arbitrary local paths that appear in normal chat text (let the conversation read naturally)
- Files containing secrets, tokens, credentials, passwords, private keys, or `.env` data (the helper rejects these)
- Files from `/tmp/` or other scratch directories that were not intentionally created for Chris to view
- Directories or non-regular files

## Usage

```python
from agent.published_artifacts import publish_artifact

try:
    url = publish_artifact(
        "/tmp/report.md",
        display_name="incident-report.md",  # optional; defaults to source basename
        subdir="bob",                       # optional; defaults to "bob"
    )
    # url → "https://assets.cp7.dev/bob/incident-report.md"
except ArtifactError as e:
    # handle failure — source missing, secret-like path, etc.
```

Then include the link in a Telegram message:

```
Here's the report: [incident-report.md](https://assets.cp7.dev/bob/incident-report.md)
```

The existing `TelegramAdapter.format_message()` converts standard markdown links
to Telegram MarkdownV2 hyperlinks automatically.

## Collision handling

If the same display name is published twice, the second copy gets a `_1`, `_2`,
etc. suffix. Original files are never overwritten.

Example:
- `report.md` (first publish)
- `report_1.md` (second publish with same name)

## Secret rejection

The helper rejects source paths and display names containing:

- `.env` (any path component ending in `.env`)
- `secret`, `token`, `credential`, `password` (as word/path components)
- `id_rsa`, `private_key`
- Filenames matching `key.<ext>` or paths containing `private/` segments
