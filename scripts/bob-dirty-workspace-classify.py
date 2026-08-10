#!/usr/bin/env python3
"""Classify dirty workspace files for Bob/Hermes dispatch guards.

Exit 0 when workspace is clean or only has generated artifacts.
Exit 1 when real source/tooling changes should block dispatch.
"""
from __future__ import annotations

import argparse
import fnmatch
import os
import subprocess
import sys
from dataclasses import dataclass, field
from typing import Iterable

GENERATED_PATTERNS: tuple[tuple[str, str], ...] = (
    ("bob-blocked-*.md", "generated report"),
    ("bob-dispatch-closeout-*.md", "generated report"),
    ("*-FINAL_REPORT.md", "generated report"),
    ("*-RUN_REPORT.md", "generated report"),
    ("*-REPORT.md", "generated report"),
    ("*-output.txt", "smoke artifact"),
    ("*-output/", "smoke artifact"),
    ("*-smoke-output*.txt", "smoke artifact"),
    ("*-test-marker.txt", "smoke artifact"),
    ("pi-notify-test-marker.txt", "smoke artifact"),
    ("*.log", "generated log"),
    ("logs/", "generated log"),
    ("agent-session-logs/", "generated log"),
    ("interrupt_debug.log", "generated log"),
    ("swap/bob-scratchpads/", "generated temp/json/payload"),
    ("bob-scratchpad.md", "generated temp/json/payload"),
    (".playwright-mcp/", "smoke artifact"),
    ("*.meta", "generated temp/json/payload"),
    ("exit_code.txt", "smoke artifact"),
    ("prompt.txt", "smoke artifact"),
    ("runner.sh", "smoke artifact"),
    ("headless-followable.log", "generated log"),
    ("session.meta.txt", "generated log"),
    ("session.tty.log", "generated log"),
    (".hermes_history", "generated log"),
    (".restart_last_processed.json", "generated temp/json/payload"),
    (".update_check", "generated temp/json/payload"),
    ("feishu_seen_message_ids.json", "generated temp/json/payload"),
    ("skills/.curator_state", "generated temp/json/payload"),
    ("skills/.dispatch-registry.json", "generated temp/json/payload"),
    ("skills/.usage.json", "generated temp/json/payload"),
    ("skills/.usage.json.lock", "generated temp/json/payload"),
    ("models.json", "generated temp/json/payload"),
    ("ollama_cloud_models_cache.json", "generated temp/json/payload"),
    ("provider_models_cache.json", "generated temp/json/payload"),
    ("kanban.db.init.lock", "generated temp/json/payload"),
    ("cache/", "generated temp/json/payload"),
    ("data/", "generated temp/json/payload"),
    ("image_cache/", "generated temp/json/payload"),
    ("memories/*.lock", "generated temp/json/payload"),
)

SOURCE_EXTENSIONS = {".py", ".sh", ".bash", ".js", ".ts", ".tsx", ".jsx", ".go", ".rs", ".yaml", ".yml"}
SOURCE_BASENAMES = {
    "HANDOFF.md",
    "SOUL.md",
    "AGENTS.md",
    "SKILL.md",
    "cp7-notify",
    "bob-dispatch",
    "bob-cursor-headless-followable",
}


@dataclass
class FileEntry:
    path: str
    status: str
    porcelain: str
    classification: str = "unknown"
    note: str = ""


@dataclass
class WorkspaceReport:
    repo: str
    branch: str
    staged: list[FileEntry] = field(default_factory=list)
    unstaged: list[FileEntry] = field(default_factory=list)
    untracked: list[FileEntry] = field(default_factory=list)
    generated: list[FileEntry] = field(default_factory=list)
    blocking: list[FileEntry] = field(default_factory=list)

    @property
    def should_block(self) -> bool:
        return bool(self.blocking)


def _git(workspace: str, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", workspace, *args],
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.stdout


def _is_git_repo(workspace: str) -> bool:
    return _git(workspace, "rev-parse", "--is-inside-work-tree").strip() == "true"


def _branch(workspace: str) -> str:
    return _git(workspace, "branch", "--show-current").strip() or "HEAD"


def _matches_generated(rel_path: str) -> tuple[bool, str]:
    norm = rel_path.replace("\\", "/")
    base = os.path.basename(norm)
    for pattern, label in GENERATED_PATTERNS:
        if pattern.endswith("/"):
            if norm.startswith(pattern) or f"/{pattern}" in f"/{norm}/":
                return True, label
        elif fnmatch.fnmatch(norm, pattern) or fnmatch.fnmatch(base, pattern):
            return True, label
    return False, ""


def _looks_like_source(rel_path: str) -> bool:
    norm = rel_path.replace("\\", "/")
    base = os.path.basename(norm)
    if base in SOURCE_BASENAMES:
        return True
    _, ext = os.path.splitext(base)
    if ext in SOURCE_EXTENSIONS:
        parts = norm.split("/")
        if parts[0] in {"bin", "scripts", "skills", "docs", "gateway", "hermes-agent", "hooks"}:
            return True
        if "skills/" in norm and base == "SKILL.md":
            return True
    return False


def _tracked_paths(workspace: str) -> set[str]:
    return {line.strip() for line in _git(workspace, "ls-files").splitlines() if line.strip()}


def _parent_dirs(tracked: set[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for entry in tracked:
        parent = entry.rsplit("/", 1)[0] if "/" in entry else "."
        counts[parent] = counts.get(parent, 0) + 1
    return counts


def _is_sparse_home_tooling_repo(tracked: set[str]) -> bool:
    return "bin/cp7-notify" in tracked and "HANDOFF.md" in tracked


def _in_tracked_scope(rel_path: str, tracked: set[str], dir_counts: dict[str, int] | None = None) -> bool:
    norm = rel_path.replace("\\", "/")
    if norm in tracked:
        return True
    parent = norm.rsplit("/", 1)[0] if "/" in norm else "."
    counts = dir_counts or _parent_dirs(tracked)
    if _is_sparse_home_tooling_repo(tracked):
        if parent == "scripts":
            return True
        if parent == "bin":
            return norm in tracked
        return False
    if parent not in counts:
        return False
    if counts[parent] == 1:
        only = next(t for t in tracked if t.rsplit("/", 1)[0] == parent)
        return norm == only
    return True


def classify_path(rel_path: str, status: str, tracked: set[str] | None = None) -> FileEntry:
    entry = FileEntry(path=rel_path, status=status, porcelain="")
    tracked_set = tracked or set()
    dir_counts = _parent_dirs(tracked_set) if tracked_set else {}
    is_gen, note = _matches_generated(rel_path)
    if is_gen:
        entry.classification = "generated artifact"
        entry.note = note
        return entry
    if status in {"staged", "unstaged"}:
        entry.classification = "source/tooling change"
        entry.note = f"tracked file {status}"
        return entry
    if tracked_set and _is_sparse_home_tooling_repo(tracked_set) and status == "untracked":
        entry.classification = "generated artifact"
        entry.note = "untracked outside sparse home tooling contract"
        return entry
    if tracked_set and not _in_tracked_scope(rel_path, tracked_set, dir_counts):
        entry.classification = "generated artifact"
        entry.note = "outside sparse repo tracked scope"
        return entry
    if _looks_like_source(rel_path):
        entry.classification = "source/tooling change"
        entry.note = "untracked source-like path"
        return entry
    entry.classification = "unknown"
    entry.note = "untracked path — review before dispatch"
    return entry


def _parse_porcelain_line(workspace: str, line: str, tracked: set[str]) -> list[FileEntry]:
    entries: list[FileEntry] = []
    if line.startswith("??"):
        rel = line[3:].strip()
        if " -> " in rel:
            rel = rel.split(" -> ", 1)[1]
        entry = classify_path(rel, "untracked", tracked)
        entry.porcelain = line
        entries.append(entry)
        return entries
    xy = line[:2]
    rel = line[3:].strip()
    if " -> " in rel:
        rel = rel.split(" -> ", 1)[1]
    if xy[0] != " ":
        entry = classify_path(rel, "staged", tracked)
        entry.porcelain = line
        entries.append(entry)
    if xy[1] != " ":
        entry = classify_path(rel, "unstaged", tracked)
        entry.porcelain = line
        entries.append(entry)
    return entries


def parse_porcelain(workspace: str) -> WorkspaceReport:
    repo = os.path.realpath(workspace)
    tracked = _tracked_paths(workspace)
    report = WorkspaceReport(repo=repo, branch=_branch(workspace))
    porcelain = _git(workspace, "status", "--porcelain")
    for line in porcelain.splitlines():
        if not line.strip():
            continue
        for entry in _parse_porcelain_line(workspace, line, tracked):
            if entry.status == "untracked":
                report.untracked.append(entry)
            elif entry.status == "staged":
                report.staged.append(entry)
            elif entry.status == "unstaged":
                report.unstaged.append(entry)

    seen: set[str] = set()
    for bucket in (report.staged, report.unstaged, report.untracked):
        for entry in bucket:
            if entry.path in seen:
                continue
            seen.add(entry.path)
            if entry.classification == "generated artifact":
                report.generated.append(entry)
            elif entry.classification in {"source/tooling change", "unknown"}:
                report.blocking.append(entry)
    return report


def _recommendation(report: WorkspaceReport) -> str:
    if not report.should_block:
        if report.generated:
            return (
                "No blocking changes. Generated artifacts present but ignored. "
                "Safe to dispatch."
            )
        return "Workspace clean. Safe to dispatch."
    items = [e.path for e in report.blocking[:8]]
    more = len(report.blocking) - len(items)
    suffix = f" (+{more} more)" if more > 0 else ""
    paths = ", ".join(items) + suffix
    return (
        f"Resolve blocking files before dispatch: {paths}. "
        "Commit intentional source edits, move generated outputs under "
        "/home/chris/swap or /home/chris/agent-session-logs, or use --allow-dirty "
        "only when Chris explicitly approves."
    )


def format_report(report: WorkspaceReport) -> str:
    lines = [
        f"REPO: {report.repo}",
        f"BRANCH: {report.branch}",
        "",
        "STAGED:",
    ]
    if report.staged:
        lines.extend(f"  {e.porcelain or e.path}  [{e.classification}]" for e in report.staged)
    else:
        lines.append("  (none)")
    lines.append("")
    lines.append("UNSTAGED:")
    if report.unstaged:
        lines.extend(f"  {e.porcelain or e.path}  [{e.classification}]" for e in report.unstaged)
    else:
        lines.append("  (none)")
    lines.append("")
    lines.append("UNTRACKED:")
    if report.untracked:
        lines.extend(f"  ?? {e.path}  [{e.classification}]" for e in report.untracked)
    else:
        lines.append("  (none)")
    lines.append("")
    lines.append("GENERATED (ignored for blocking):")
    if report.generated:
        lines.extend(f"  {e.path}  [{e.note}]" for e in report.generated)
    else:
        lines.append("  (none)")
    lines.append("")
    lines.append("BLOCKING:")
    if report.blocking:
        lines.extend(f"  {e.path}  [{e.classification}: {e.note}]" for e in report.blocking)
    else:
        lines.append("  (none)")
    lines.append("")
    lines.append(f"SHOULD_BLOCK: {'yes' if report.should_block else 'no'}")
    lines.append(f"RECOMMENDATION: {_recommendation(report)}")
    return "\n".join(lines)


def format_compact_evidence(report: WorkspaceReport) -> str:
    lines: list[str] = []
    for label, items in (
        ("staged", report.staged),
        ("unstaged", report.unstaged),
        ("untracked", report.untracked),
        ("generated_ignored", report.generated),
        ("blocking", report.blocking),
    ):
        for e in items:
            lines.append(f"{label}: {e.porcelain or e.path} [{e.classification}]")
    lines.append(f"repo: {report.repo}")
    lines.append(f"branch: {report.branch}")
    lines.append(f"recommendation: {_recommendation(report)}")
    return "\n".join(lines)


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Classify Bob/Hermes dirty workspace files")
    parser.add_argument("workspace", help="Git workspace path")
    parser.add_argument("--check", action="store_true", help="Exit 1 when dispatch should block")
    parser.add_argument("--compact", action="store_true", help="Compact evidence output")
    args = parser.parse_args(list(argv) if argv is not None else None)

    workspace = os.path.realpath(args.workspace)
    if not os.path.isdir(workspace):
        print(f"ERROR: workspace not found: {workspace}", file=sys.stderr)
        return 2
    if not _is_git_repo(workspace):
        print("DIRTY_CHECK: skipped (not a git repo)")
        return 0

    report = parse_porcelain(workspace)
    if args.compact:
        print(format_compact_evidence(report))
    else:
        print(format_report(report))

    if args.check:
        return 1 if report.should_block else 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
