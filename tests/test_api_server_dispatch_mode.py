"""Tests for /v1/runs dispatch orchestrator fast path."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from agent.dispatch_mode import (
    DISPATCH_LEAN_TOOLSETS,
    DISPATCH_ORCHESTRATOR_CONTRACT,
    DISPATCH_PREFLIGHT_BUDGET_EXCEEDED,
    DEFAULT_MAX_PRE_DISPATCH_CALLS,
    DEFAULT_MAX_PRE_DISPATCH_CONTEXT_TOKENS,
    DispatchModeConfig,
    DispatchPreflightBudget,
    apply_dispatch_agent_kwargs,
    attach_dispatch_mode,
    build_dispatch_startup_measurement,
    build_dispatch_system_prompt_parts,
    check_dispatch_preflight_before_api_call,
    parse_dispatch_mode_request,
)
from agent.prompt_builder import MEMORY_GUIDANCE, SKILLS_GUIDANCE
from gateway.config import PlatformConfig
from gateway.platforms.api_server import (
    APIServerAdapter,
    cors_middleware,
    security_headers_middleware,
)


def _make_adapter() -> APIServerAdapter:
    return APIServerAdapter(PlatformConfig(enabled=True, extra={}))


def _create_runs_app(adapter: APIServerAdapter) -> web.Application:
    mws = [mw for mw in (cors_middleware, security_headers_middleware) if mw is not None]
    app = web.Application(middlewares=mws)
    app["api_server_adapter"] = adapter
    app.router.add_post("/v1/runs", adapter._handle_runs)
    return app


def _patch_create_agent_runtime(monkeypatch, captured: dict, fake_agent_cls):
    monkeypatch.setattr("run_agent.AIAgent", fake_agent_cls)
    monkeypatch.setattr(
        "gateway.run._resolve_runtime_agent_kwargs",
        lambda: {
            "provider": "openrouter",
            "api_key": "sk-global",
            "base_url": "https://openrouter.ai/api/v1",
            "api_mode": "chat_completions",
        },
    )
    monkeypatch.setattr("gateway.run._resolve_gateway_model", lambda: "global/model")
    monkeypatch.setattr("gateway.run._load_gateway_config", lambda: {})
    monkeypatch.setattr(
        "gateway.run.GatewayRunner._load_fallback_model", staticmethod(lambda: None)
    )
    monkeypatch.setattr(
        "hermes_cli.tools_config._get_platform_tools",
        lambda *_: {"file", "terminal", "delegation", "skills", "memory", "web"},
    )


class FakeAgent:
    instances = []

    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)
        self.valid_tool_names = sorted(
            {
                "read_file",
                "write_file",
                "terminal",
                "delegate_task",
            }
        )
        self.dispatch_mode = False
        self._dispatch_preflight_budget = None
        FakeAgent.instances.append(self)


class TestDispatchModeParsing:
    def test_missing_opt_in_is_disabled(self):
        config, err = parse_dispatch_mode_request({"input": "hi"}, {})
        assert config is None
        assert err is None

    def test_false_opt_in_is_disabled(self):
        config, err = parse_dispatch_mode_request({"dispatch_mode": False}, {})
        assert config is None
        assert err is None

    def test_true_opt_in_enables_defaults(self):
        config, err = parse_dispatch_mode_request({"dispatch_mode": True}, {})
        assert err is None
        assert config is not None
        assert config.enabled is True
        assert config.max_pre_dispatch_calls == DEFAULT_MAX_PRE_DISPATCH_CALLS
        assert config.max_pre_dispatch_context_tokens == (
            DEFAULT_MAX_PRE_DISPATCH_CONTEXT_TOKENS
        )

    def test_header_opt_in(self):
        config, err = parse_dispatch_mode_request(
            {},
            {"X-Hermes-Dispatch-Mode": "true"},
        )
        assert err is None
        assert config is not None and config.enabled is True

    def test_malformed_dispatch_mode_rejected(self):
        config, err = parse_dispatch_mode_request({"dispatch_mode": "maybe"}, {})
        assert config is None
        assert err is not None

    def test_custom_budgets_from_object(self):
        config, err = parse_dispatch_mode_request(
            {
                "dispatch_mode": {
                    "max_pre_dispatch_calls": 3,
                    "max_pre_dispatch_context_tokens": 12000,
                }
            },
            {},
        )
        assert err is None
        assert config.max_pre_dispatch_calls == 3
        assert config.max_pre_dispatch_context_tokens == 12000


class TestDispatchAgentConstruction:
    def test_ordinary_runs_unchanged(self, monkeypatch):
        captured = {}
        FakeAgent.instances.clear()

        class RecordingAgent(FakeAgent):
            def __init__(self, **kwargs):
                captured.update(kwargs)
                super().__init__(**kwargs)

        adapter = _make_adapter()
        _patch_create_agent_runtime(monkeypatch, captured, RecordingAgent)
        monkeypatch.setattr(adapter, "_ensure_session_db", lambda: None)

        adapter._create_agent(session_id="s1")

        assert captured.get("skip_context_files") is not True
        assert captured.get("skip_memory") is not True
        assert "skills" in captured.get("enabled_toolsets", [])
        assert getattr(RecordingAgent.instances[-1], "dispatch_mode", False) is False

    def test_dispatch_mode_lean_construction(self, monkeypatch):
        captured = {}
        FakeAgent.instances.clear()

        class RecordingAgent(FakeAgent):
            def __init__(self, **kwargs):
                captured.update(kwargs)
                super().__init__(**kwargs)

        adapter = _make_adapter()
        _patch_create_agent_runtime(monkeypatch, captured, RecordingAgent)
        monkeypatch.setattr(adapter, "_ensure_session_db", lambda: None)

        config = DispatchModeConfig(enabled=True)
        adapter._create_agent(session_id="s1", dispatch_mode_config=config)

        assert captured["skip_context_files"] is True
        assert captured["skip_memory"] is True
        assert captured["enabled_toolsets"] == sorted(DISPATCH_LEAN_TOOLSETS)
        assert RecordingAgent.instances[-1].dispatch_mode is True
        assert RecordingAgent.instances[-1]._dispatch_preflight_budget is not None


class TestDispatchSystemPrompt:
    def test_contract_present_exactly_once(self):
        agent = SimpleNamespace(
            dispatch_mode=True,
            skip_context_files=True,
            skip_memory=True,
            valid_tool_names=["read_file", "terminal", "delegate_task"],
            enabled_toolsets=list(DISPATCH_LEAN_TOOLSETS),
            ephemeral_system_prompt=None,
        )
        attach_dispatch_mode(agent, DispatchModeConfig(enabled=True))
        measurement = build_dispatch_startup_measurement(agent)
        parts = build_dispatch_system_prompt_parts(agent)

        assert measurement["contract_present"] is True
        assert measurement["contract_occurrences"] == 1
        assert parts["stable"].count(DISPATCH_ORCHESTRATOR_CONTRACT) == 1
        assert parts["volatile"] == ""

    def test_ordinary_prompt_not_dispatch_lean(self):
        agent = SimpleNamespace(
            dispatch_mode=False,
            skip_context_files=False,
            skip_memory=False,
            valid_tool_names=["read_file", "memory", "skills_list"],
            enabled_toolsets=["file", "memory", "skills"],
            ephemeral_system_prompt=None,
            _memory_store=None,
            _memory_manager=None,
            _memory_enabled=False,
            _user_profile_enabled=False,
            platform="api_server",
            pass_session_id=False,
            session_id="run_test",
            model="test-model",
            provider="test-provider",
            _tool_use_enforcement=False,
        )

        def _build_system_prompt(system_message=None):
            return "\n\n".join([MEMORY_GUIDANCE, SKILLS_GUIDANCE, "x" * 5000])

        agent._build_system_prompt = _build_system_prompt
        measurement = build_dispatch_startup_measurement(agent)
        assert DISPATCH_ORCHESTRATOR_CONTRACT not in str(measurement)


class TestDispatchMeasurement:
    def test_measurement_is_deterministic(self):
        agent = SimpleNamespace(
            dispatch_mode=True,
            skip_context_files=True,
            skip_memory=True,
            valid_tool_names=["read_file", "terminal", "delegate_task"],
            enabled_toolsets=list(DISPATCH_LEAN_TOOLSETS),
            ephemeral_system_prompt="Do the thing.",
            platform="api_server",
        )
        attach_dispatch_mode(agent, DispatchModeConfig(enabled=True))
        tools = [
            {
                "type": "function",
                "function": {"name": "read_file", "description": "read", "parameters": {}},
            }
        ]
        messages = [{"role": "user", "content": "hello"}]
        first = build_dispatch_startup_measurement(agent, messages=messages, tools=tools)
        second = build_dispatch_startup_measurement(agent, messages=messages, tools=tools)
        assert first == second
        assert first["token_estimate_method"] == "rough_local_estimate"
        assert first["dominant_component"] in first["token_breakdown_rough"]
        assert first["components"]["switches"]["skip_memory"] is True


class TestDispatchBudgetEnforcement:
    def test_call_budget_sentinel(self):
        agent = SimpleNamespace(
            dispatch_mode=True,
            skip_context_files=True,
            skip_memory=True,
            valid_tool_names=["delegate_task"],
            enabled_toolsets=list(DISPATCH_LEAN_TOOLSETS),
            ephemeral_system_prompt=None,
            platform="api_server",
        )
        config = DispatchModeConfig(enabled=True, max_pre_dispatch_calls=2)
        attach_dispatch_mode(agent, config)

        failure = check_dispatch_preflight_before_api_call(
            agent,
            next_call_number=3,
            messages=[{"role": "user", "content": "x"}],
            tools=[],
            system_prompt="",
        )
        assert failure is not None
        assert failure["error"] == DISPATCH_PREFLIGHT_BUDGET_EXCEEDED
        assert failure["final_response"] == DISPATCH_PREFLIGHT_BUDGET_EXCEEDED
        report = failure["dispatch_budget_report"]
        assert report["api_calls_so_far"] == 2
        assert report["max_pre_dispatch_calls"] == 2
        assert report["token_estimate_method"] == "rough_local_estimate"

    def test_default_call_budget_call_5_allowed_call_6_blocked(self):
        agent = SimpleNamespace(
            dispatch_mode=True,
            skip_context_files=True,
            skip_memory=True,
            valid_tool_names=["delegate_task"],
            enabled_toolsets=list(DISPATCH_LEAN_TOOLSETS),
            ephemeral_system_prompt=None,
            platform="api_server",
        )
        attach_dispatch_mode(agent, DispatchModeConfig(enabled=True))
        kwargs = dict(
            messages=[{"role": "user", "content": "x"}],
            tools=[],
            system_prompt="",
        )
        assert (
            check_dispatch_preflight_before_api_call(
                agent, next_call_number=DEFAULT_MAX_PRE_DISPATCH_CALLS, **kwargs
            )
            is None
        )
        failure = check_dispatch_preflight_before_api_call(
            agent, next_call_number=DEFAULT_MAX_PRE_DISPATCH_CALLS + 1, **kwargs
        )
        assert failure is not None
        assert failure["error"] == DISPATCH_PREFLIGHT_BUDGET_EXCEEDED

    def test_context_budget_sentinel(self):
        agent = SimpleNamespace(
            dispatch_mode=True,
            skip_context_files=True,
            skip_memory=True,
            valid_tool_names=["read_file"],
            enabled_toolsets=list(DISPATCH_LEAN_TOOLSETS),
            ephemeral_system_prompt="x" * 200_000,
            platform="api_server",
        )
        config = DispatchModeConfig(
            enabled=True,
            max_pre_dispatch_context_tokens=1000,
        )
        attach_dispatch_mode(agent, config)

        failure = check_dispatch_preflight_before_api_call(
            agent,
            next_call_number=1,
            messages=[{"role": "user", "content": "y" * 50_000}],
            tools=[
                {
                    "type": "function",
                    "function": {
                        "name": f"tool_{i}",
                        "description": "d" * 500,
                        "parameters": {"type": "object"},
                    },
                }
                for i in range(40)
            ],
            system_prompt="",
        )
        assert failure is not None
        assert failure["error"] == DISPATCH_PREFLIGHT_BUDGET_EXCEEDED
        assert failure["dispatch_budget_report"]["budget_reason"] == "context_token_budget"

    def test_default_context_budget_25000_allowed_25001_blocked(self, monkeypatch):
        from agent.model_metadata import estimate_tokens_rough

        agent = SimpleNamespace(
            dispatch_mode=True,
            skip_context_files=True,
            skip_memory=True,
            valid_tool_names=["read_file"],
            enabled_toolsets=list(DISPATCH_LEAN_TOOLSETS),
            ephemeral_system_prompt=None,
            platform="api_server",
        )
        attach_dispatch_mode(agent, DispatchModeConfig(enabled=True))

        def _fake_measurement(*_args, **_kwargs):
            return {"total_tokens_rough": estimate_tokens_rough("x")}

        monkeypatch.setattr(
            "agent.dispatch_mode.build_dispatch_startup_measurement",
            lambda *_a, **_k: {"total_tokens_rough": 25000},
        )
        assert (
            check_dispatch_preflight_before_api_call(
                agent,
                next_call_number=1,
                messages=[],
                tools=[],
                system_prompt="",
            )
            is None
        )

        monkeypatch.setattr(
            "agent.dispatch_mode.build_dispatch_startup_measurement",
            lambda *_a, **_k: {"total_tokens_rough": 25001},
        )
        failure = check_dispatch_preflight_before_api_call(
            agent,
            next_call_number=1,
            messages=[],
            tools=[],
            system_prompt="",
        )
        assert failure is not None
        assert failure["dispatch_budget_report"]["budget_reason"] == "context_token_budget"

    def test_budget_inactive_for_non_dispatch(self):
        agent = SimpleNamespace(dispatch_mode=False)
        assert (
            check_dispatch_preflight_before_api_call(
                agent,
                next_call_number=99,
                messages=[],
                tools=[],
                system_prompt="",
            )
            is None
        )

    def test_budget_report_contains_consumers(self):
        budget = DispatchPreflightBudget(DispatchModeConfig(enabled=True))
        measurement = {
            "total_tokens_rough": 10,
            "token_breakdown_rough": {"tool_schemas": 6, "messages": 4},
            "dominant_component": "tool_schemas",
        }
        assert budget.check_before_api_call(next_call_number=1, measurement=measurement) is None
        result = budget.check_before_api_call(
            next_call_number=DEFAULT_MAX_PRE_DISPATCH_CALLS + 1,
            measurement=measurement,
        )
        assert "dominant_component" in result["dispatch_budget_report"]


class TestDispatchRunsEndpoint:
    @pytest.mark.asyncio
    async def test_dispatch_mode_passed_to_create_agent(self):
        adapter = _make_adapter()
        app = _create_runs_app(adapter)
        async with TestClient(TestServer(app)) as cli:
            with patch.object(adapter, "_create_agent") as mock_create:
                mock_agent = MagicMock()
                mock_agent.run_conversation.return_value = {"final_response": "done"}
                mock_agent.session_prompt_tokens = 0
                mock_agent.session_completion_tokens = 0
                mock_agent.session_total_tokens = 0
                mock_create.return_value = mock_agent

                resp = await cli.post(
                    "/v1/runs",
                    json={"input": "hello", "dispatch_mode": True},
                )
                assert resp.status == 202
                kwargs = mock_create.call_args.kwargs
                config = kwargs.get("dispatch_mode_config")
                assert config is not None
                assert config.enabled is True

    @pytest.mark.asyncio
    async def test_ordinary_runs_omits_dispatch_config(self):
        adapter = _make_adapter()
        app = _create_runs_app(adapter)
        async with TestClient(TestServer(app)) as cli:
            with patch.object(adapter, "_create_agent") as mock_create:
                mock_agent = MagicMock()
                mock_agent.run_conversation.return_value = {"final_response": "done"}
                mock_agent.session_prompt_tokens = 0
                mock_agent.session_completion_tokens = 0
                mock_agent.session_total_tokens = 0
                mock_create.return_value = mock_agent

                resp = await cli.post("/v1/runs", json={"input": "hello"})
                assert resp.status == 202
                assert mock_create.call_args.kwargs.get("dispatch_mode_config") is None

    @pytest.mark.asyncio
    async def test_malformed_dispatch_mode_returns_400(self):
        adapter = _make_adapter()
        app = _create_runs_app(adapter)
        async with TestClient(TestServer(app)) as cli:
            resp = await cli.post(
                "/v1/runs",
                json={"input": "hello", "dispatch_mode": "nope"},
            )
            assert resp.status == 400

    @pytest.mark.asyncio
    async def test_dispatch_mode_does_not_spawn_services(self):
        adapter = _make_adapter()
        app = _create_runs_app(adapter)
        async with TestClient(TestServer(app)) as cli:
            with patch.object(adapter, "_create_agent") as mock_create:
                mock_agent = MagicMock()
                mock_agent.run_conversation.return_value = {"final_response": "done"}
                mock_agent.session_prompt_tokens = 0
                mock_agent.session_completion_tokens = 0
                mock_agent.session_total_tokens = 0
                mock_create.return_value = mock_agent

                with patch("subprocess.run") as mock_subprocess:
                    with patch("os.system") as mock_system:
                        resp = await cli.post(
                            "/v1/runs",
                            json={"input": "hello", "dispatch_mode": True},
                        )
                        assert resp.status == 202
                        mock_subprocess.assert_not_called()
                        mock_system.assert_not_called()


class TestDispatchStartupReduction:
    def test_dispatch_fixture_smaller_than_default_api_server(self):
        base_agent = SimpleNamespace(
            dispatch_mode=False,
            skip_context_files=False,
            skip_memory=False,
            valid_tool_names=[
                "read_file",
                "skills_list",
                "skill_view",
                "memory",
                "web_search",
            ],
            enabled_toolsets=["file", "skills", "memory", "web"],
            ephemeral_system_prompt=None,
            platform="api_server",
        )

        def _fat_prompt(system_message=None):
            return "\n\n".join(
                [MEMORY_GUIDANCE, SKILLS_GUIDANCE, "x" * 8000, "y" * 4000]
            )

        base_agent._build_system_prompt = _fat_prompt

        dispatch_agent = SimpleNamespace(
            dispatch_mode=True,
            skip_context_files=True,
            skip_memory=True,
            valid_tool_names=["read_file", "terminal", "delegate_task"],
            enabled_toolsets=list(DISPATCH_LEAN_TOOLSETS),
            ephemeral_system_prompt=None,
            platform="api_server",
        )
        attach_dispatch_mode(dispatch_agent, DispatchModeConfig(enabled=True))

        base_parts = {"stable": _fat_prompt(), "context": "", "volatile": ""}
        dispatch_parts = build_dispatch_system_prompt_parts(dispatch_agent)
        base_size = sum(len(v) for v in base_parts.values())
        dispatch_size = sum(len(v) for v in dispatch_parts.values())
        assert dispatch_size < base_size

        base_measurement = build_dispatch_startup_measurement(base_agent)
        dispatch_measurement = build_dispatch_startup_measurement(dispatch_agent)
        assert (
            dispatch_measurement["total_tokens_rough"]
            < base_measurement["total_tokens_rough"]
        )


class TestApplyDispatchAgentKwargs:
    def test_apply_dispatch_agent_kwargs(self):
        updated = apply_dispatch_agent_kwargs(
            {"enabled_toolsets": ["web"]},
            DispatchModeConfig(enabled=True),
        )
        assert updated["skip_context_files"] is True
        assert updated["enabled_toolsets"] == sorted(DISPATCH_LEAN_TOOLSETS)
