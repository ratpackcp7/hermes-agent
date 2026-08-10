"""Dispatch/orchestrator fast-path — lean mode, budgets, and preflight guards.

Activated via ``dispatch.orchestrator_mode`` in config.yaml (preferred) or the
``HERMES_DISPATCH_MODE`` env bridge. Off by default; normal interactive Hermes
is unchanged when inactive.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional

from agent.model_metadata import estimate_request_tokens_rough, estimate_tokens_rough

DISPATCH_PREFLIGHT_BUDGET_EXCEEDED = "DISPATCH_PREFLIGHT_BUDGET_EXCEEDED"

DISPATCH_TOOLSET_NAME = "dispatch_orchestrator"

# Lean orchestration surface — excludes web/browser/vision/messaging/implement tools.
DISPATCH_ORCHESTRATOR_TOOLS: tuple[str, ...] = (
    "read_file",
    "search_files",
    "terminal",
    "process",
    "delegate_task",
    "skills_list",
    "skill_view",
    "clarify",
)

DISPATCH_STABLE_IDENTITY = (
    "You are Bob/Foreman — a dispatch orchestrator. Your job is to read the "
    "task SPEC, verify capability/headroom, ensure a fresh worktree, and "
    "dispatch a worker. Do not implement source changes unless the SPEC "
    "explicitly assigns implementation to you or the task is a tiny direct op."
)

DISPATCH_ORCHESTRATION_SEQUENCE = (
    "Default build sequence (strict): "
    "SPEC -> capability/headroom check -> fresh worktree -> dispatch worker. "
    "Load Git/worktree/production detail only when that boundary is crossed."
)

DISPATCH_SAFETY_CONTRACT = (
    "Safety/production boundary (once): irreversible or production-impacting "
    "actions require explicit user authorization — never bypass for speed. "
    "Protected main/master is never mutated directly; use a fresh worktree. "
    "Dirty protected checkouts fail closed or require a new worktree per policy."
)

DISPATCH_APPROVAL_CONTRACT = (
    "Approval boundary: dangerous commands, secret prompts, and production "
    "touches still require normal Hermes approval flows — dispatch lean mode "
    "does not disable them."
)


def _truthy_env(name: str) -> Optional[bool]:
    raw = os.environ.get(name)
    if raw is None:
        return None
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def load_dispatch_config() -> Dict[str, Any]:
    """Return dispatch.* settings with documented defaults."""
    defaults = {
        "orchestrator_mode": False,
        "preflight_token_ceiling": 25_000,
        "first_call_token_target": 10_000,
        "max_preflight_model_calls": 5,
    }
    try:
        from hermes_cli.config import load_config_readonly

        cfg = load_config_readonly().get("dispatch") or {}
        if isinstance(cfg, dict):
            merged = dict(defaults)
            merged.update({k: v for k, v in cfg.items() if v is not None})
            return merged
    except Exception:
        pass
    return defaults


def is_dispatch_orchestrator_mode() -> bool:
    """True when dispatch lean mode is active for this process."""
    env_val = _truthy_env("HERMES_DISPATCH_MODE")
    if env_val is not None:
        return env_val
    return bool(load_dispatch_config().get("orchestrator_mode", False))


def bridge_dispatch_mode_to_env() -> None:
    """Mirror config.yaml dispatch.orchestrator_mode into HERMES_DISPATCH_MODE."""
    if os.environ.get("HERMES_DISPATCH_MODE") is not None:
        return
    if load_dispatch_config().get("orchestrator_mode"):
        os.environ["HERMES_DISPATCH_MODE"] = "1"


def build_dispatch_skills_index(skill_names: Iterable[str]) -> str:
    """Compact skill pointers — names only, no full SKILL.md bodies."""
    names = sorted({str(n).strip() for n in skill_names if str(n).strip()})
    if not names:
        return ""
    return (
        "Skills (compact — use skill_view on demand): "
        + ", ".join(f"`{n}`" for n in names)
    )


def build_dispatch_system_prompt_parts(
    agent: Any,
    system_message: Optional[str] = None,
    *,
    skill_names: Optional[Iterable[str]] = None,
) -> Dict[str, str]:
    """Lean dispatch prompt tiers — materially smaller than interactive baseline."""
    stable_parts = [
        DISPATCH_STABLE_IDENTITY,
        DISPATCH_SAFETY_CONTRACT,
        DISPATCH_APPROVAL_CONTRACT,
        DISPATCH_ORCHESTRATION_SEQUENCE,
    ]
    context_parts: List[str] = []
    if system_message:
        context_parts.append(system_message.strip())
    spec_path = os.environ.get("HERMES_DISPATCH_SPEC_PATH", "").strip()
    if spec_path:
        context_parts.append(f"SPEC path (read on demand): {spec_path}")
    volatile_parts: List[str] = []
    if skill_names is not None:
        skills_block = build_dispatch_skills_index(skill_names)
        if skills_block:
            volatile_parts.append(skills_block)
    # Session/model line intentionally omitted from stable prefix — volatile tier only.
    model = getattr(agent, "model", "") or ""
    provider = getattr(agent, "provider", "") or ""
    if model or provider:
        volatile_parts.append(f"Model: {model or 'unknown'} | Provider: {provider or 'unknown'}")
    return {
        "stable": "\n\n".join(p for p in stable_parts if p),
        "context": "\n\n".join(p for p in context_parts if p),
        "volatile": "\n\n".join(p for p in volatile_parts if p),
    }


def requires_production_authorization(action: str) -> bool:
    """Return True when *action* is production-impacting and needs explicit go-ahead."""
    lowered = (action or "").lower()
    markers = (
        "production",
        "deploy",
        "restart service",
        "systemctl restart",
        "docker restart",
        "migrate",
        "drop table",
        "rm -rf /",
        "push --force",
    )
    return any(m in lowered for m in markers)


@dataclass
class DispatchBlocker:
    """Deterministic NO-GO for dispatch preflight."""

    code: str
    message: str
    actionable: bool = True

    def as_text(self) -> str:
        return f"DISPATCH_BLOCKER:{self.code}:{self.message}"


@dataclass
class DispatchPreflightBudget:
    """Hard pre-dispatch budgets with deterministic sentinel on exceed."""

    preflight_token_ceiling: int = 25_000
    first_call_token_target: int = 10_000
    max_preflight_model_calls: int = 5
    model_call_count: int = 0
    worker_dispatched: bool = False
    consumers: Dict[str, int] = field(default_factory=dict)

    @classmethod
    def from_config(cls) -> "DispatchPreflightBudget":
        cfg = load_dispatch_config()
        return cls(
            preflight_token_ceiling=int(cfg.get("preflight_token_ceiling", 25_000)),
            first_call_token_target=int(cfg.get("first_call_token_target", 10_000)),
            max_preflight_model_calls=int(cfg.get("max_preflight_model_calls", 5)),
        )

    def record_consumer(self, name: str, tokens: int) -> None:
        if tokens <= 0:
            return
        self.consumers[name] = self.consumers.get(name, 0) + tokens

    def consumer_report(self) -> str:
        if not self.consumers:
            return "budget_consumers: none recorded"
        ranked = sorted(self.consumers.items(), key=lambda kv: (-kv[1], kv[0]))
        parts = [f"{name}={count}" for name, count in ranked]
        return "budget_consumers: " + ", ".join(parts)

    def exceeded_message(self) -> str:
        return f"{DISPATCH_PREFLIGHT_BUDGET_EXCEEDED}\n{self.consumer_report()}"

    def check_preflight(
        self,
        *,
        messages: List[Dict[str, Any]],
        tool_schemas: Optional[List[Dict[str, Any]]] = None,
        system_prompt: str = "",
    ) -> Optional[str]:
        """Return budget-exceeded sentinel or None when within limits."""
        if self.worker_dispatched:
            return None
        self.model_call_count += 1
        total = estimate_request_tokens_rough(
            messages or [],
            system_prompt=system_prompt or "",
            tools=tool_schemas or [],
        )
        sys_tokens = estimate_tokens_rough(system_prompt or "")
        self.record_consumer("system_prompt", sys_tokens)
        if tool_schemas:
            self.record_consumer(
                "tool_schemas",
                estimate_tool_schema_tokens(list(tool_schemas)),
            )
        self.record_consumer("messages_and_tools", total)
        self.record_consumer("total_estimated_input", total)
        if self.model_call_count == 1 and total > self.first_call_token_target:
            self.record_consumer("first_call_ceiling", self.first_call_token_target)
            return self.exceeded_message()
        if total > self.preflight_token_ceiling:
            self.record_consumer("preflight_ceiling", self.preflight_token_ceiling)
            return self.exceeded_message()
        if self.model_call_count > self.max_preflight_model_calls:
            self.record_consumer("model_call_ceiling", self.max_preflight_model_calls)
            return self.exceeded_message()
        return None


def session_dispatched_worker(messages: Iterable[dict] | None) -> bool:
    """True when delegate_task already ran in this conversation."""
    if not messages:
        return False
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        if msg.get("role") == "tool" and msg.get("name") == "delegate_task":
            return True
        if msg.get("role") == "assistant":
            for tc in msg.get("tool_calls") or []:
                fn = tc.get("function") if isinstance(tc, dict) else None
                if isinstance(fn, dict) and fn.get("name") == "delegate_task":
                    return True
    return False


def evaluate_dirty_checkout(
    *,
    is_dirty: bool,
    is_protected_branch: bool,
    worktree_available: bool,
) -> Optional[DispatchBlocker]:
    if not is_dirty:
        return None
    if is_protected_branch and not worktree_available:
        return DispatchBlocker(
            "DIRTY_PROTECTED_CHECKOUT",
            "Protected branch is dirty and no fresh worktree is available.",
        )
    if worktree_available:
        return DispatchBlocker(
            "DIRTY_REQUIRES_WORKTREE",
            "Checkout is dirty — create/use a fresh worktree before dispatch.",
        )
    return DispatchBlocker(
        "DIRTY_CHECKOUT",
        "Checkout is dirty — resolve or isolate changes before dispatch.",
    )


def evaluate_worktree_capability(*, worktree_capable: bool) -> Optional[DispatchBlocker]:
    if worktree_capable:
        return None
    return DispatchBlocker(
        "WORKTREE_UNAVAILABLE",
        "Worktree capability is unavailable (NO-GO).",
    )


def evaluate_worker_headroom(*, headroom_ok: bool, reason: str = "") -> Optional[DispatchBlocker]:
    if headroom_ok:
        return None
    detail = reason.strip() or "Worker/headroom check failed."
    return DispatchBlocker("WORKER_HEADROOM", detail)


def estimate_tool_schema_tokens(tool_schemas: List[Dict[str, Any]]) -> int:
    """Measure tool-schema token cost deterministically (for docs/tests)."""
    try:
        payload = json.dumps(tool_schemas, sort_keys=True, separators=(",", ":"))
    except TypeError:
        payload = str(tool_schemas)
    return estimate_tokens_rough(payload)


def apply_dispatch_toolset_pin(
    enabled_toolsets: Optional[List[str]],
) -> List[str]:
    """When dispatch mode is active, pin to the lean orchestration toolset."""
    if not is_dispatch_orchestrator_mode():
        return list(enabled_toolsets) if enabled_toolsets else []
    return [DISPATCH_TOOLSET_NAME]
