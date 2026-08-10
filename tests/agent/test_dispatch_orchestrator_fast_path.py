"""Hermetic regression tests for dispatch/orchestrator fast-path."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from agent.dispatch_orchestrator import (
    DISPATCH_APPROVAL_CONTRACT,
    DISPATCH_PREFLIGHT_BUDGET_EXCEEDED,
    DISPATCH_SAFETY_CONTRACT,
    DISPATCH_TOOLSET_NAME,
    DispatchPreflightBudget,
    apply_dispatch_toolset_pin,
    build_dispatch_system_prompt_parts,
    evaluate_dirty_checkout,
    evaluate_worktree_capability,
    evaluate_worker_headroom,
    estimate_tool_schema_tokens,
    is_dispatch_orchestrator_mode,
    requires_production_authorization,
    session_dispatched_worker,
)
from agent.system_prompt import build_system_prompt_parts
from toolsets import resolve_toolset


def _make_agent(**overrides):
    base = dict(
        load_soul_identity=False,
        skip_context_files=False,
        valid_tool_names=set(),
        _task_completion_guidance=False,
        _tool_use_enforcement=False,
        _environment_probe=False,
        _kanban_worker_guidance="",
        _memory_store=None,
        _memory_manager=None,
        model="test/model",
        provider="test",
        platform="cli",
        pass_session_id=False,
        session_id="",
    )
    base.update(overrides)
    return SimpleNamespace(**base)


@pytest.fixture
def dispatch_env(monkeypatch, tmp_path):
    home = tmp_path / ".hermes"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setenv("HERMES_DISPATCH_MODE", "1")
    yield home


class TestDispatchModeGating:
    def test_off_by_default(self, monkeypatch, tmp_path):
        home = tmp_path / ".hermes"
        home.mkdir()
        monkeypatch.setenv("HERMES_HOME", str(home))
        monkeypatch.delenv("HERMES_DISPATCH_MODE", raising=False)
        assert is_dispatch_orchestrator_mode() is False

    def test_env_activation(self, dispatch_env):
        assert is_dispatch_orchestrator_mode() is True

    def test_config_activation(self, monkeypatch, tmp_path):
        home = tmp_path / ".hermes"
        home.mkdir()
        home.joinpath("config.yaml").write_text(
            "dispatch:\n  orchestrator_mode: true\n",
            encoding="utf-8",
        )
        monkeypatch.setenv("HERMES_HOME", str(home))
        monkeypatch.delenv("HERMES_DISPATCH_MODE", raising=False)
        assert is_dispatch_orchestrator_mode() is True


class TestLeanPrompt:
    def test_minimal_spec_dispatch_lean_prompt(self, dispatch_env):
        parts = build_dispatch_system_prompt_parts(
            _make_agent(),
            system_message="SPEC: ship feature X",
            skill_names=["git", "foreman"],
        )
        stable = parts["stable"]
        assert DISPATCH_SAFETY_CONTRACT in stable
        assert DISPATCH_APPROVAL_CONTRACT in stable
        assert stable.count(DISPATCH_SAFETY_CONTRACT) == 1
        assert stable.count(DISPATCH_APPROVAL_CONTRACT) == 1
        assert "SPEC: ship feature X" in parts["context"]
        assert "`git`" in parts["volatile"]
        assert "SOUL" not in stable

    def test_large_spec_stays_bounded(self, dispatch_env):
        big_spec = "SPEC:\n" + ("line\n" * 5000)
        parts = build_dispatch_system_prompt_parts(
            _make_agent(),
            system_message=big_spec,
        )
        assert parts["context"].startswith("SPEC:")
        assert len(parts["stable"]) < len(big_spec)
        assert "HERMES_AGENT_HELP" not in parts["stable"]

    def test_normal_interactive_unchanged_when_off(self, monkeypatch, tmp_path):
        home = tmp_path / ".hermes"
        home.mkdir()
        monkeypatch.setenv("HERMES_HOME", str(home))
        monkeypatch.delenv("HERMES_DISPATCH_MODE", raising=False)
        agent = _make_agent(valid_tool_names={"terminal"})
        with (
            patch("run_agent.load_soul_md", return_value=""),
            patch("run_agent.build_nous_subscription_prompt", return_value=""),
            patch("run_agent.build_environment_hints", return_value=""),
            patch("run_agent.build_context_files_prompt", return_value=""),
        ):
            parts = build_system_prompt_parts(agent)
        assert "Bob/Foreman" not in parts["stable"]


class TestWorktreeAndCapability:
    def test_dirty_protected_requires_worktree(self):
        blocker = evaluate_dirty_checkout(
            is_dirty=True,
            is_protected_branch=True,
            worktree_available=False,
        )
        assert blocker is not None
        assert blocker.code == "DIRTY_PROTECTED_CHECKOUT"

    def test_dirty_with_worktree_actionable(self):
        blocker = evaluate_dirty_checkout(
            is_dirty=True,
            is_protected_branch=True,
            worktree_available=True,
        )
        assert blocker is not None
        assert blocker.code == "DIRTY_REQUIRES_WORKTREE"

    def test_missing_worktree_capability_no_go(self):
        blocker = evaluate_worktree_capability(worktree_capable=False)
        assert blocker is not None
        assert blocker.code == "WORKTREE_UNAVAILABLE"
        assert "NO-GO" in blocker.message

    def test_worker_headroom_failure(self):
        blocker = evaluate_worker_headroom(headroom_ok=False, reason="pool exhausted")
        assert blocker is not None
        assert blocker.code == "WORKER_HEADROOM"


class TestBudgetEnforcement:
    def test_budget_exceeded_sentinel_and_report(self):
        budget = DispatchPreflightBudget(
            preflight_token_ceiling=100,
            first_call_token_target=50,
            max_preflight_model_calls=5,
        )
        huge = "x" * 10_000
        msg = budget.check_preflight(
            messages=[{"role": "user", "content": huge}],
            system_prompt=huge,
        )
        assert msg is not None
        assert msg.startswith(DISPATCH_PREFLIGHT_BUDGET_EXCEEDED)
        assert "budget_consumers:" in msg

    def test_worker_dispatched_skips_budget(self):
        budget = DispatchPreflightBudget(preflight_token_ceiling=10)
        budget.worker_dispatched = True
        assert budget.check_preflight(
            messages=[{"role": "user", "content": "x" * 5000}],
            system_prompt="y" * 5000,
        ) is None

    def test_session_dispatched_worker_detection(self):
        messages = [
            {
                "role": "assistant",
                "tool_calls": [
                    {"id": "1", "function": {"name": "delegate_task", "arguments": "{}"}},
                ],
            },
            {"role": "tool", "name": "delegate_task", "content": "ok", "tool_call_id": "1"},
        ]
        assert session_dispatched_worker(messages) is True


class TestToolset:
    def test_dispatch_toolset_excludes_unrelated_tools(self):
        tools = set(resolve_toolset(DISPATCH_TOOLSET_NAME))
        assert "read_file" in tools
        assert "delegate_task" in tools
        assert "web_search" not in tools
        assert "browser_navigate" not in tools
        assert "vision_analyze" not in tools
        assert "image_generate" not in tools

    def test_dispatch_mode_pins_toolset(self, dispatch_env):
        pinned = apply_dispatch_toolset_pin(["hermes-cli", "web"])
        assert pinned == [DISPATCH_TOOLSET_NAME]

    def test_tool_schema_token_cost_measurable(self):
        schema = [{"type": "function", "function": {"name": "read_file", "parameters": {}}}]
        assert estimate_tool_schema_tokens(schema) > 0


class TestSafetyBoundary:
    def test_production_action_requires_authorization(self):
        assert requires_production_authorization("deploy to production") is True
        assert requires_production_authorization("read the spec file") is False


class TestMinimalSpecDispatchIntegration:
    def test_worktree_worker_within_budget_contract(self, dispatch_env):
        budget = DispatchPreflightBudget.from_config()
        parts = build_dispatch_system_prompt_parts(
            _make_agent(),
            system_message="SPEC: minimal",
        )
        prompt = "\n\n".join(parts[k] for k in ("stable", "context", "volatile") if parts[k])
        first = budget.check_preflight(
            messages=[{"role": "user", "content": "dispatch worker for SPEC"}],
            system_prompt=prompt,
            tool_schemas=json.loads(
                json.dumps(
                    [{"type": "function", "function": {"name": "delegate_task", "parameters": {}}}]
                )
            ),
        )
        assert first is None or not str(first).startswith(DISPATCH_PREFLIGHT_BUDGET_EXCEEDED)
