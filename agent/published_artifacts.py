"""
published_artifacts — Publish Bob files as clickable HTTPS artifacts.

Usage:
    from agent.published_artifacts import publish_artifact

    try:
        url = publish_artifact("/tmp/report.md")
        # → "https://assets.cp7.dev/bob/report.md"
        telegram_text = [
            f"Here's the report: [{clean_name}]({url})",
            f"Full file: [{clean_name}]({url})",
        ][0]
    except ArtifactError as e:
        # handle / report failure
"""

from __future__ import annotations

import os
import re
import shutil
from pathlib import Path

# ── Configuration ──────────────────────────────────────────────────────────

# Served root on the filesystem (nginx serves this at assets.cp7.dev)
_SERVED_ROOT = Path("/home/chris/cp7-design")

# URL base that maps to the served root
_URL_BASE = "https://assets.cp7.dev"

# Bob artifact subdirectory under the served root
_ARTIFACT_SUBDIR = "bob"

# Secret-like name/pattern rejection — conservative policy
# Secret-like words — matched as whole words or exact path segments,
# so "monkey_patch.py" or "sticky_notes.md" are NOT rejected.
_SECRET_PATTERNS: list[re.Pattern] = [
    # .env file
    re.compile(r"(?:^|[/\\])\.env$", re.IGNORECASE),
    # Path/file ending in .env
    re.compile(r"\.env$", re.IGNORECASE),
    # Secret-like words as path components — matches "credentials", "secret_key", etc.
    # Uses _ and / separators to avoid matching inside normal words.
    re.compile(r"(?:^|[/\\_])(?:secret|token|credential|password)[s]?(?:$|[._\\/])", re.IGNORECASE),
    # key.xxx file
    re.compile(r"(?:^|[/\\])[^/\\]*?key\.[^/\\]+$", re.IGNORECASE),
    # private (at word boundary, path start, or followed by _ or .)
    re.compile(r"(?:^|[/\\]|_)private[_.]|private_key", re.IGNORECASE),
    # id_rsa
    re.compile(r"(?:^|[/\\])id_rsa(?:\b|\.|$)", re.IGNORECASE),
]


class ArtifactError(Exception):
    """Raised when artifact publishing fails."""


def _is_secret_path(path: str | Path) -> bool:
    """Return True if *path* or any of its components looks secret-like."""
    path_str = str(path)
    full_lower = path_str.lower()
    name = Path(path_str).name.lower()

    for pattern in _SECRET_PATTERNS:
        if pattern.search(full_lower) or pattern.search(name):
            return True
    return False


def _sanitize_filename(name: str) -> str:
    """Strip dangerous characters from a filename, preserving extension."""
    # Remove path separators and null bytes
    clean = re.sub(r"[/\\\x00]", "_", name)
    # Remove leading dots (hidden files)
    clean = re.sub(r"^\.+", "", clean)
    # Collapse repeated underscores/dashes
    clean = re.sub(r"[_\-]{2,}", "_", clean)
    # Strip leading/trailing whitespace and dots
    clean = clean.strip("._- \t")
    if not clean:
        clean = "artifact"
    return clean


def _collision_path(dest: Path) -> Path:
    """Return a non-colliding path by appending a short hash if needed."""
    if not dest.exists():
        return dest
    stem = dest.stem
    suffix = dest.suffix
    parent = dest.parent
    # Use a counter file to generate unique suffixes
    tag = 1
    while True:
        candidate = parent / f"{stem}_{tag}{suffix}"
        if not candidate.exists():
            return candidate
        tag += 1


def publish_artifact(
    local_path: str | Path,
    display_name: str | None = None,
    subdir: str | None = _ARTIFACT_SUBDIR,
) -> str:
    """Copy a local file into the published artifact area and return its URL.

    Args:
        local_path: Absolute path to the source file.
        display_name: Optional override for the published filename.
            If omitted, the original basename is used (after sanitization).
        subdir: Subdirectory under the served root. Defaults to "bob".

    Returns:
        The public HTTPS URL of the published artifact.

    Raises:
        ArtifactError: If the source file is missing, not a regular file,
            is a secret-like path, or is a directory.
    """
    src = Path(local_path).resolve()

    # 1. Source must exist and be a regular file
    if not src.exists():
        raise ArtifactError(f"Source does not exist: {src}")
    if not src.is_file():
        raise ArtifactError(f"Source is not a regular file: {src}")

    # 2. Reject secret-like source paths
    if _is_secret_path(src):
        raise ArtifactError(f"Source path rejected (secret-like): {src}")

    # 3. Determine display filename
    raw_name = display_name if display_name else src.name
    # Reject unsafe display names before sanitization
    if display_name is not None:
        if any(c in display_name for c in ('/', '\\')) or '..' in display_name:
            raise ArtifactError(f"Display name contains unsafe characters: {display_name}")
    clean_name = _sanitize_filename(raw_name)
    if not clean_name:
        clean_name = "artifact"

    # 4. Reject secret-like display names (already sanitized, but double-check)
    if _is_secret_path(clean_name):
        raise ArtifactError(f"Display name rejected (secret-like): {clean_name}")

    # 5. Build destination path
    artifact_dir = _SERVED_ROOT / (subdir or _ARTIFACT_SUBDIR)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    # Ensure artifact directory has correct permissions
    artifact_dir.chmod(0o755)

    dest = artifact_dir / clean_name
    dest = _collision_path(dest)

    # 6. Copy (not move) — preserve original for debugging
    shutil.copy2(src, dest)
    # Set published file permissions to 0644
    dest.chmod(0o644)

    # 7. Build and return the public URL
    rel_path = dest.relative_to(_SERVED_ROOT)
    url = f"{_URL_BASE}/{rel_path.as_posix()}"
    return url
