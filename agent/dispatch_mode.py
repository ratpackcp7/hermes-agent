"""Dispatch/orchestrator fast path for Bob /v1/runs callers.

Opt-in via request body ``dispatch_mode`` or ``X-Hermes-Dispatch-Mode`` header.
Inactive for all other agent entry points.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Tuple

DISPATCH_PREFLIGHT_BUDGET_EXCEEDED = "DISPATCH_PREFLIGHT_BUDGET_EXCEEDED"

DEFAULT_MAX_PRE_DISPATCH_CALLS = 5
DEFAULT_MAX_PRE_DISPATCH_CONTEXT_TOKENS = 25000

# Lean toolsets: SPEC/task read, bounded terminal/git, worker delegation.
DISPATCH_LEAN_TOOLSETS: Tuple[str, ...] = ("file", "terminal", "delegation")

DISPATCH_ORCHESTRATOR_CONTRACT = """\
Dispatch orchestrator contract (binding):
- Obey the supplied task/SPEC exactly; do not improvise scope.
- Never modify protected main; use a fresh git worktree for implementation work.
- Production-impacting actions (service restarts, deploys, kills, infra changes) require explicit authorization in the task.
- Before launching a worker, select capability tier and headroom when routing is needed.
- Foreman sequence: SPEC -> capability/headroom -> fresh worktree -> worker.
- Delegate normal build/implementation work; do not drift into long implementation loops yourself.
- If pre-dispatch exploration exceeds budget, stop and report: DISPATCH_PREFLIGHT_BUDGET_EXCEEDED."""

_TOKEN_ESTIMATE_LABEL = "rough_local_estimate"


@dataclass
class DispatchModeConfig:
    enabled: bool = False
    max_pre_dispatch_calls: int = DEFAULT_MAX_PRE_DISPATCH_CALLS
    max_pre_dispatch_context_tokens: int = DEFAULT_MAX_PRE_DISPATCH_CONTEXT_TOKENS


@dataclass
class DispatchPreflightBudget:
    """Request-scoped pre-dispatch budget tracker."""

    config: DispatchModeConfig
    api_calls: int = 0
    complete: bool = False
    completion_reason: str = ""
    last_context_tokens: Optional[int] = None
    last_measurement: Dict[str, Any] = field(default_factory=dict)

    def mark_preflight_complete(self, reason: str) -> None:
        self.complete = True
        self.completion_reason = reason

    def record_context_measurement(self, measurement: Dict[str, Any]) -> None:
        self.last_measurement = dict(measurement)
        tokens = measurement.get("total_tokens_rough")
        if isinstance(tokens, int):
            self.last_context_tokens = tokens

    def check_before_api_call(
        self,
        *,
        next_call_number: int,
        measurement: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        if not self.config.enabled or self.complete:
            return None
        self.record_context_measurement(measurement)
        if next_call_number > self.config.max_pre_dispatch_calls:
            return self._exceeded_report(
                reason="api_call_budget",
                detail=(
                    f"pre-dispatch API call budget exceeded "
                    f"({self.config.max_pre_dispatch_calls} allowed, "
                    f"attempting call #{next_call_number})"
                ),
                next_call_number=next_call_number,
            )
        context_tokens = measurement.get("total_tokens_rough")
        if (
            isinstance(context_tokens, int)
            and context_tokens > self.config.max_pre_dispatch_context_tokens
        ):
            return self._exceeded_report(
                reason="context_token_budget",
                detail=(
                    f"pre-dispatch context budget exceeded "
                    f"({self.config.max_pre_dispatch_context_tokens} token ceiling, "
                    f"{_TOKEN_ESTIMATE_LABEL}={context_tokens})"
                ),
                next_call_number=next_call_number,
            )
        return None

    def _exceeded_report(
        self,
        *,
        reason: str,
        detail: str,
        next_call_number: int,
    ) -> Dict[str, Any]:
        consumers = dict(self.last_measurement)
        consumers.update(
            {
                "api_calls_so_far": max(0, next_call_number - 1),
                "attempted_call_number": next_call_number,
                "max_pre_dispatch_calls": self.config.max_pre_dispatch_calls,
                "max_pre_dispatch_context_tokens": self.config.max_pre_dispatch_context_tokens,
                "budget_reason": reason,
                "token_estimate_method": _TOKEN_ESTIMATE_LABEL,
            }
        )
        return {
            "failed": True,
            "final_response": DISPATCH_PREFLIGHT_BUDGET_EXCEEDED,
            "error": DISPATCH_PREFLIGHT_BUDGET_EXCEEDED,
            "dispatch_budget_exceeded": True,
            "dispatch_budget_report": consumers,
            "detail": detail,
        }


def _coerce_bool(value: Any) -> Optional[bool]:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    if isinstance(value, int) and value in {0, 1}:
        return bool(value)
    return None


def _parse_budget_int(
    raw: Any,
    *,
    field_name: str,
    default: int,
) -> Tuple[Optional[int], Optional[str]]:
    if raw is None:
        return default, None
    if isinstance(raw, bool):
        return None, f"dispatch_mode.{field_name} must be an integer"
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None, f"dispatch_mode.{field_name} must be an integer"
    if value < 1:
        return None, f"dispatch_mode.{field_name} must be >= 1"
    return value, None


def parse_dispatch_mode_request(
    body: Any,
    headers: Optional[Mapping[str, str]] = None,
) -> Tuple[Optional[DispatchModeConfig], Optional[str]]:
    """Parse dispatch opt-in from JSON body and/or X-Hermes-Dispatch-Mode header."""
    enabled: Optional[bool] = None
    max_calls = DEFAULT_MAX_PRE_DISPATCH_CALLS
    max_context = DEFAULT_MAX_PRE_DISPATCH_CONTEXT_TOKENS

    if headers:
        header_val = headers.get("X-Hermes-Dispatch-Mode")
        if header_val is not None and str(header_val).strip():
            header_bool = _coerce_bool(header_val)
            if header_bool is None:
                return None, "X-Hermes-Dispatch-Mode must be a boolean (true/false/1/0)"
            enabled = header_bool

    if isinstance(body, dict) and "dispatch_mode" in body:
        raw = body.get("dispatch_mode")
        if raw is None:
            enabled = False
        elif isinstance(raw, bool):
            enabled = raw
        elif isinstance(raw, (str, int)):
            body_bool = _coerce_bool(raw)
            if body_bool is None:
                return None, "dispatch_mode must be a boolean or options object"
            enabled = body_bool
        elif isinstance(raw, dict):
            if "enabled" in raw:
                opt_bool = _coerce_bool(raw.get("enabled"))
                if opt_bool is None:
                    return None, "dispatch_mode.enabled must be a boolean"
                enabled = opt_bool
            else:
                enabled = True
            parsed_calls, err = _parse_budget_int(
                raw.get("max_pre_dispatch_calls"),
                field_name="max_pre_dispatch_calls",
                default=max_calls,
            )
            if err:
                return None, err
            max_calls = parsed_calls or max_calls
            parsed_context, err = _parse_budget_int(
                raw.get("max_pre_dispatch_context_tokens"),
                field_name="max_pre_dispatch_context_tokens",
                default=max_context,
            )
            if err:
                return None, err
            max_context = parsed_context or max_context
        else:
            return None, "dispatch_mode must be a boolean or options object"

    if enabled is None or not enabled:
        return None, None

    return (
        DispatchModeConfig(
            enabled=True,
            max_pre_dispatch_calls=max_calls,
            max_pre_dispatch_context_tokens=max_context,
        ),
        None,
    )


def apply_dispatch_agent_kwargs(
    agent_kwargs: Dict[str, Any],
    config: DispatchModeConfig,
) -> Dict[str, Any]:
    """Return lean agent kwargs for dispatch orchestration mode."""
    updated = dict(agent_kwargs)
    updated["skip_context_files"] = True
    updated["skip_memory"] = True
    updated["enabled_toolsets"] = sorted(DISPATCH_LEAN_TOOLSETS)
    return updated


def attach_dispatch_mode(agent: Any, config: DispatchModeConfig) -> None:
    agent.dispatch_mode = True
    agent._dispatch_mode_config = config
    agent._dispatch_preflight_budget = DispatchPreflightBudget(config)


def build_dispatch_system_prompt_parts(
    agent: Any,
    system_message: Optional[str] = None,
) -> Dict[str, str]:
    """Lean system prompt tiers for Bob dispatch /v1/runs orchestrator mode."""
    from agent.prompt_builder import DEFAULT_AGENT_IDENTITY

    stable_parts = [DEFAULT_AGENT_IDENTITY, DISPATCH_ORCHESTRATOR_CONTRACT]
    context_parts: List[str] = []
    if system_message is not None:
        context_parts.append(system_message)
    return {
        "stable": "\n\n".join(stable_parts),
        "context": "\n\n".join(p for p in context_parts if p and p.strip()),
        "volatile": "",
    }


def note_dispatch_tool_calls(agent: Any, assistant_message: Any) -> None:
    """Mark pre-dispatch budget complete when worker dispatch or clarify fires."""
    budget: Optional[DispatchPreflightBudget] = getattr(
        agent, "_dispatch_preflight_budget", None
    )
    if budget is None or budget.complete:
        return
    tool_calls = getattr(assistant_message, "tool_calls", None) or []
    for tool_call in tool_calls:
        fn = getattr(tool_call, "function", None)
        name = getattr(fn, "name", None) if fn is not None else None
        if name == "delegate_task":
            budget.mark_preflight_complete("worker_dispatched")
            return
        if name == "clarify":
            budget.mark_preflight_complete("actionable_blocker")
            return


def _resolve_system_prompt_parts(
    agent: Any,
    system_prompt: str = "",
) -> Dict[str, str]:
    if getattr(agent, "dispatch_mode", False):
        return build_dispatch_system_prompt_parts(agent)
    if hasattr(agent, "_build_system_prompt") and callable(agent._build_system_prompt):
        full = agent._build_system_prompt()
        return {"stable": full, "context": "", "volatile": ""}
    return {"stable": system_prompt or "", "context": "", "volatile": ""}


def build_dispatch_startup_measurement(
    agent: Any,
    *,
    messages: Optional[List[Dict[str, Any]]] = None,
    tools: Optional[List[Dict[str, Any]]] = None,
    system_prompt: str = "",
) -> Dict[str, Any]:
    """Deterministic decomposition of dispatch startup payload (unit-testable)."""
    from agent.model_metadata import (
        estimate_messages_tokens_rough,
        estimate_tokens_rough,
    )

    def _estimate_tools_tokens_rough(tool_defs: List[Dict[str, Any]]) -> int:
        if not tool_defs:
            return 0
        return (len(str(tool_defs)) + 3) // 4

    parts = _resolve_system_prompt_parts(agent, system_prompt=system_prompt)
    stable_chars = len(parts.get("stable") or "")
    context_chars = len(parts.get("context") or "")
    volatile_chars = len(parts.get("volatile") or "")
    ephemeral = getattr(agent, "ephemeral_system_prompt", None) or ""
    ephemeral_chars = len(ephemeral) if isinstance(ephemeral, str) else 0

    stable_tokens = estimate_tokens_rough(parts.get("stable") or "")
    context_tokens = estimate_tokens_rough(parts.get("context") or "")
    volatile_tokens = estimate_tokens_rough(parts.get("volatile") or "")
    ephemeral_tokens = estimate_tokens_rough(ephemeral) if ephemeral else 0
    message_tokens = estimate_messages_tokens_rough(messages or [])
    tool_tokens = _estimate_tools_tokens_rough(tools or [])

    total_tokens_rough = (
        stable_tokens
        + context_tokens
        + volatile_tokens
        + ephemeral_tokens
        + message_tokens
        + tool_tokens
    )

    components = {
        "system_prompt_stable_chars": stable_chars,
        "system_prompt_context_chars": context_chars,
        "system_prompt_volatile_chars": volatile_chars,
        "ephemeral_prompt_chars": ephemeral_chars,
        "tool_schema_count": len(tools or []),
        "message_count": len(messages or []),
        "enabled_toolsets": sorted(getattr(agent, "enabled_toolsets", None) or []),
        "switches": {
            "dispatch_mode": bool(getattr(agent, "dispatch_mode", False)),
            "skip_context_files": bool(getattr(agent, "skip_context_files", False)),
            "skip_memory": bool(getattr(agent, "skip_memory", False)),
        },
    }

    token_breakdown = {
        "system_prompt_stable": stable_tokens,
        "system_prompt_context": context_tokens,
        "system_prompt_volatile": volatile_tokens,
        "ephemeral_prompt": ephemeral_tokens,
        "messages": message_tokens,
        "tool_schemas": tool_tokens,
    }
    dominant = max(token_breakdown.items(), key=lambda item: item[1])

    return {
        "components": components,
        "token_breakdown_rough": token_breakdown,
        "total_tokens_rough": total_tokens_rough,
        "token_estimate_method": _TOKEN_ESTIMATE_LABEL,
        "dominant_component": dominant[0],
        "dominant_component_tokens_rough": dominant[1],
        "contract_present": DISPATCH_ORCHESTRATOR_CONTRACT in (parts.get("stable") or ""),
        "contract_occurrences": (parts.get("stable") or "").count(
            DISPATCH_ORCHESTRATOR_CONTRACT
        ),
    }


def check_dispatch_preflight_before_api_call(
    agent: Any,
    *,
    next_call_number: int,
    messages: List[Dict[str, Any]],
    tools: Optional[List[Dict[str, Any]]],
    system_prompt: str,
) -> Optional[Dict[str, Any]]:
    budget: Optional[DispatchPreflightBudget] = getattr(
        agent, "_dispatch_preflight_budget", None
    )
    if budget is None or not budget.config.enabled or budget.complete:
        return None
    measurement = build_dispatch_startup_measurement(
        agent,
        messages=messages,
        tools=tools,
        system_prompt=system_prompt,
    )
    result = budget.check_before_api_call(
        next_call_number=next_call_number,
        measurement=measurement,
    )
    if result is not None:
        budget.mark_preflight_complete("budget_exceeded")
    else:
        budget.api_calls = next_call_number
    return result


def format_budget_exceeded_message(report: Dict[str, Any]) -> str:
    """Human-readable budget failure with consumer breakdown."""
    payload = {
        "sentinel": DISPATCH_PREFLIGHT_BUDGET_EXCEEDED,
        "report": report.get("dispatch_budget_report") or report,
    }
    return DISPATCH_PREFLIGHT_BUDGET_EXCEEDED + "\n" + json.dumps(payload, sort_keys=True)
