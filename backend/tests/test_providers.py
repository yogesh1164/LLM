import asyncio
import sys
from types import ModuleType, SimpleNamespace

import pytest
from pydantic import SecretStr

from app import providers
from app.config import Settings
from app.providers import ProviderConfigurationError
from app.research import extract_grounding_sources


def test_provider_selection_defaults_to_gemini() -> None:
    config = Settings(_env_file=None, ai_provider="gemini", gemini_api_key=SecretStr("hidden-test-key"))
    assert config.ai_provider == "gemini"
    assert config.active_model == "gemini-3.8-flash"
    assert config.gemini_search_grounding_enabled is False
    providers.validate_provider(config)


def test_missing_provider_key_is_reported_safely() -> None:
    config = Settings(_env_file=None, ai_provider="gemini", gemini_api_key=None)
    with pytest.raises(ProviderConfigurationError, match="Gemini API key is not configured"):
        providers.validate_provider(config)


def test_openai_provider_requires_its_own_key() -> None:
    config = Settings(_env_file=None, ai_provider="openai", openai_api_key=None)
    with pytest.raises(ProviderConfigurationError, match="OpenAI API key is not configured"):
        providers.validate_provider(config)


def test_unsupported_gemini_model_is_rejected() -> None:
    config = Settings(_env_file=None, ai_provider="gemini", gemini_api_key=SecretStr("secret"),
                      gemini_model="gpt-5-mini")
    with pytest.raises(ProviderConfigurationError, match="Gemini model is unsupported"):
        providers.validate_provider(config)


def test_gemini_agent_stage_uses_native_provider_interface() -> None:
    config = Settings(_env_file=None, ai_provider="gemini", gemini_api_key=SecretStr("do-not-log"))

    result = providers.build_agent("Research", "Research carefully", config=config)

    assert result.name == "Research"
    assert result.instructions == "Research carefully"
    assert result.provider_agent is None


def test_gemini_stage_execution_is_mocked(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.providers import StageResult

    config = Settings(_env_file=None, ai_provider="gemini", gemini_api_key=SecretStr("test-only"))
    stage = providers.build_agent("Research", "Use evidence", config=config)
    calls = []

    async def fake_generate(name, instructions, prompt, *, timeout_seconds=None, config):
        calls.append((name, instructions, prompt, timeout_seconds))
        return StageResult(final_output="Mocked Gemini response", input_tokens=4, output_tokens=2)

    monkeypatch.setattr("app.research.generate_gemini_stage", fake_generate)
    result = asyncio.run(providers.run_agent_stage(stage, "Find evidence", config=config))

    assert result.final_output == "Mocked Gemini response"
    assert result.input_tokens == 4
    assert calls == [("Research", "Use evidence", "Find evidence", None)]


def test_custom_gemini_agent_passes_saved_generation_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    config = Settings(_env_file=None, gemini_api_key=SecretStr("test-only"))
    recorded = {}

    async def fake_generate(*args, **kwargs):
        recorded["args"] = args
        recorded["kwargs"] = kwargs
        return providers.StageResult("ok", input_tokens=3, output_tokens=2)

    monkeypatch.setattr("app.research.generate_gemini_stage", fake_generate)
    result = asyncio.run(providers.run_custom_gemini_agent(
        name="Saved", instructions="Follow the brief", prompt="Do work", model=config.gemini_model,
        temperature=0.3, max_output_tokens=256, timeout_seconds=12, config=config,
    ))
    assert result.final_output == "ok"
    assert recorded["kwargs"]["model"] == config.gemini_model
    assert recorded["kwargs"]["temperature"] == 0.3
    assert recorded["kwargs"]["max_output_tokens"] == 256


def test_custom_gemini_agent_rejects_unconfigured_model() -> None:
    config = Settings(_env_file=None, gemini_api_key=SecretStr("test-only"))
    with pytest.raises(ProviderConfigurationError, match="saved Gemini model is unsupported"):
        asyncio.run(providers.run_custom_gemini_agent(
            name="Saved", instructions="Follow", prompt="Do work", model="gemini-other",
            temperature=0.2, max_output_tokens=128, timeout_seconds=12, config=config,
        ))


def test_openai_agent_sdk_adapter_is_optional_and_mocked(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []

    class FakeAgent:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    fake_agents = ModuleType("agents")
    fake_agents.Agent = FakeAgent
    fake_agents.WebSearchTool = lambda **kwargs: kwargs
    fake_agents.set_default_openai_key = lambda key: calls.append(key)

    class FakeRunner:
        @staticmethod
        async def run(agent, prompt, *, run_config=None):
            calls.append(prompt)
            return SimpleNamespace(
                final_output="Mocked OpenAI response",
                context_wrapper=SimpleNamespace(usage=SimpleNamespace(
                    input_tokens=3, output_tokens=5, input_tokens_details=None,
                )),
                raw_responses=[],
            )

    class FakeModelSettings:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    class FakeRunConfig:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    fake_agents.Runner = FakeRunner
    fake_agents.ModelSettings = FakeModelSettings
    fake_agents.RunConfig = FakeRunConfig
    monkeypatch.setitem(sys.modules, "agents", fake_agents)
    config = Settings(_env_file=None, ai_provider="openai", openai_api_key=SecretStr("test-only"))

    result = providers.build_agent("Analysis", "Analyze", config=config)

    assert result.name == "Analysis"
    assert result.provider_agent.kwargs["model"] == config.openai_model
    assert calls == ["test-only"]
    run_result = asyncio.run(providers.run_agent_stage(result, "Analyze evidence", config=config))
    assert run_result.final_output == "Mocked OpenAI response"
    assert (run_result.input_tokens, run_result.output_tokens) == (3, 5)
    assert calls[-1] == "Analyze evidence"


def test_gemini_grounding_returns_only_real_urls_and_deduplicates() -> None:
    response = SimpleNamespace(candidates=[SimpleNamespace(grounding_metadata=SimpleNamespace(
        grounding_chunks=[
            SimpleNamespace(web=SimpleNamespace(uri="https://example.org/a", title="Evidence")),
            SimpleNamespace(web=SimpleNamespace(uri="https://example.org/a", title="Evidence")),
            SimpleNamespace(web=SimpleNamespace(uri="javascript:bad", title="Invalid")),
        ],
    ))])
    assert extract_grounding_sources(response) == [
        {"url": "https://example.org/a", "title": "Evidence"},
    ]


def test_gemini_sdk_call_and_search_tool_are_mocked(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.research import generate_gemini_stage

    recorded = {}
    response = SimpleNamespace(
        output_text="Evidence-backed response",
        usage=SimpleNamespace(total_input_tokens=6, total_output_tokens=4),
        steps=[SimpleNamespace(content=[SimpleNamespace(annotations=[SimpleNamespace(
            type="url_citation", url="https://example.org/ref", title="Reference",
        )])])],
    )

    class FakeClient:
        def __init__(self, *, api_key, http_options):
            recorded["api_key"] = api_key
            recorded["http_options"] = http_options
            self.interactions = SimpleNamespace(create=self.create_interaction)

        def create_interaction(self, **kwargs):
            recorded["request"] = kwargs
            return response

        def close(self):
            recorded["closed"] = True

    fake_google = ModuleType("google")
    fake_genai = ModuleType("google.genai")
    fake_genai.Client = FakeClient
    fake_google.genai = fake_genai
    monkeypatch.setitem(sys.modules, "google", fake_google)
    monkeypatch.setitem(sys.modules, "google.genai", fake_genai)
    config = Settings(
        _env_file=None,
        ai_provider="gemini",
        gemini_api_key=SecretStr("test-only"),
        gemini_search_grounding_enabled=True,
    )

    result = asyncio.run(generate_gemini_stage(
        "Research", "Use citations", "Find sources", timeout_seconds=17, config=config
    ))

    assert result.final_output == "Evidence-backed response"
    assert (result.input_tokens, result.output_tokens) == (6, 4)
    assert result.sources == ({"url": "https://example.org/ref", "title": "Reference"},)
    assert recorded["request"]["model"] == config.gemini_model
    assert recorded["request"]["tools"] == [{"type": "google_search"}]
    assert recorded["request"]["system_instruction"] == "Use citations"
    assert 0 < recorded["http_options"]["timeout"] <= 17_000
    assert recorded["http_options"]["retry_options"] == {"attempts": 1}
    assert recorded["closed"] is True


@pytest.mark.parametrize("failures, succeeds, expected_calls", [(1, True, 2), (2, False, 3)])
def test_gemini_503_retries_are_bounded_and_can_succeed(
    monkeypatch: pytest.MonkeyPatch, failures: int, succeeds: bool, expected_calls: int,
) -> None:
    from app.providers import ProviderRequestError
    from app.research import generate_gemini_stage

    calls = 0

    class FakeClient:
        def __init__(self, **kwargs):
            self.interactions = SimpleNamespace(create=self.create)

        def create(self, **kwargs):
            nonlocal calls
            calls += 1
            if not succeeds or calls <= failures:
                error = RuntimeError("503 UNAVAILABLE: temporary backend outage")
                error.status_code = 503
                raise error
            return SimpleNamespace(output_text="ok", usage=None)

        def close(self):
            pass

    fake_google = ModuleType("google")
    fake_genai = ModuleType("google.genai")
    fake_genai.Client = FakeClient
    fake_google.genai = fake_genai
    monkeypatch.setitem(sys.modules, "google", fake_google)
    monkeypatch.setitem(sys.modules, "google.genai", fake_genai)
    monkeypatch.setattr("app.research.random.uniform", lambda low, high: 0)
    config = Settings(_env_file=None, gemini_api_key=SecretStr("test-only"),
                      provider_retry_attempts=2)
    if succeeds:
        result = asyncio.run(generate_gemini_stage("Report", "Write", "prompt", config=config))
        assert result.final_output == "ok"
    else:
        with pytest.raises(ProviderRequestError, match="temporary backend outage"):
            asyncio.run(generate_gemini_stage("Report", "Write", "prompt", config=config))
    assert calls == expected_calls


def test_gemini_quota_429_does_not_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.providers import ProviderRequestError
    from app.research import generate_gemini_stage

    calls = 0

    class FakeClient:
        def __init__(self, **kwargs):
            self.interactions = SimpleNamespace(create=self.create)

        def create(self, **kwargs):
            nonlocal calls
            calls += 1
            error = RuntimeError("429 quota exceeded: daily limit")
            error.status_code = 429
            raise error

        def close(self):
            pass

    fake_google, fake_genai = ModuleType("google"), ModuleType("google.genai")
    fake_genai.Client = FakeClient
    fake_google.genai = fake_genai
    monkeypatch.setitem(sys.modules, "google", fake_google)
    monkeypatch.setitem(sys.modules, "google.genai", fake_genai)
    config = Settings(_env_file=None, gemini_api_key=SecretStr("test-only"), provider_retry_attempts=3)
    with pytest.raises(ProviderRequestError):
        asyncio.run(generate_gemini_stage("Report", "Write", "prompt", config=config))
    assert calls == 1


def test_gemini_timeout_is_not_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    import time

    from app.research import generate_gemini_stage

    calls = 0

    class FakeClient:
        def __init__(self, **kwargs):
            self.interactions = SimpleNamespace(create=self.create)

        def create(self, **kwargs):
            nonlocal calls
            calls += 1
            time.sleep(0.05)

        def close(self):
            pass

    fake_google, fake_genai = ModuleType("google"), ModuleType("google.genai")
    fake_genai.Client = FakeClient
    fake_google.genai = fake_genai
    monkeypatch.setitem(sys.modules, "google", fake_google)
    monkeypatch.setitem(sys.modules, "google.genai", fake_genai)
    config = Settings(_env_file=None, gemini_api_key=SecretStr("test-only"),
                      provider_retry_attempts=3)
    with pytest.raises(TimeoutError):
        asyncio.run(generate_gemini_stage("Report", "Write", "prompt", timeout_seconds=0.01,
                                          config=config))
    assert calls == 1


def test_workflow_runs_all_five_agents_and_persists_citations(monkeypatch) -> None:
    from app import database, workflow

    monkeypatch.setattr(workflow.settings, "ai_provider", "gemini")
    task_id = database.create_task("Check the agent path")
    agents = {name: name for name in ("orchestrator", "research", "analysis", "report", "review")}
    cited = [{"url": "https://example.org/source", "title": "Source"}]

    def fake_build_agents():
        return agents

    calls: list[str] = []

    async def fake_run(agent, prompt, **kwargs):
        from app.providers import StageResult

        calls.append(agent)
        return StageResult(
            final_output=f"{agent} output", input_tokens=2, output_tokens=3,
            sources=tuple(cited) if agent == "research" else (),
        )

    monkeypatch.setattr(workflow, "build_agents", fake_build_agents)
    monkeypatch.setattr(workflow, "run_agent_stage", fake_run)
    events = []

    async def collect(event):
        events.append(event)

    result = asyncio.run(workflow.run_workflow("Check the agent path", task_id, collect))
    database.update_task(task_id, status="completed", result={"sources": [s.model_dump(mode="json") for s in result["sources"]]},
                         total_tokens=result["total_tokens"])

    assert calls == ["orchestrator", "research", "analysis", "report", "review"]
    assert result["total_tokens"] == 25
    assert str(result["sources"][0].url) == "https://example.org/source"
    assert [event["agent"] for event in events if event["type"] == "stage" and event["status"] == "running"] == [
        "Orchestrator", "Research", "Analysis", "Report", "Review",
    ]
    assert database.get_task(task_id)["result"]["sources"][0]["url"] == "https://example.org/source"
