"""Provider-independent agent stage interface and provider adapters."""

from dataclasses import dataclass
from typing import Any

from app.config import Settings, settings


class ProviderConfigurationError(ValueError):
    """Raised when the selected provider cannot be configured safely."""


class ProviderRequestError(RuntimeError):
    """Provider failure retaining its HTTP status and SDK diagnostic."""

    def __init__(self, status_code: int | None, provider_message: str):
        self.status_code = status_code
        self.provider_message = provider_message
        super().__init__(provider_message)


@dataclass(frozen=True)
class AgentStage:
    name: str
    instructions: str
    provider_agent: Any = None


@dataclass(frozen=True)
class StageResult:
    final_output: str
    input_tokens: int = 0
    output_tokens: int = 0
    cached_input_tokens: int = 0
    sources: tuple[dict[str, str], ...] = ()


def validate_provider(config: Settings = settings) -> None:
    if config.ai_provider == "gemini":
        if not config.gemini_api_key:
            raise ProviderConfigurationError("Gemini API key is not configured")
        if not config.gemini_model.startswith("gemini-"):
            raise ProviderConfigurationError("Gemini model is unsupported")
    elif config.ai_provider == "openai":
        if not config.openai_api_key:
            raise ProviderConfigurationError("OpenAI API key is not configured")
        if not config.openai_model:
            raise ProviderConfigurationError("The configured OpenAI model is invalid")
    else:
        raise ProviderConfigurationError("The configured AI provider is unsupported")


def build_agent(name: str, instructions: str, *, tools: list | None = None,
                config: Settings = settings) -> AgentStage:
    """Build a provider-neutral stage, creating an Agents SDK agent only for OpenAI."""
    validate_provider(config)
    if config.ai_provider == "gemini":
        return AgentStage(name=name, instructions=instructions)

    try:
        from agents import Agent, set_default_openai_key
    except ImportError as exc:
        raise ProviderConfigurationError(
            "OpenAI support is unavailable; install the backend openai extra"
        ) from exc

    set_default_openai_key(config.openai_api_key.get_secret_value())
    return AgentStage(
        name=name,
        instructions=instructions,
        provider_agent=Agent(
            name=name,
            instructions=instructions,
            model=config.openai_model,
            tools=tools or [],
        ),
    )


async def run_agent_stage(
    stage: AgentStage,
    prompt: str,
    *,
    timeout_seconds: int | None = None,
    config: Settings = settings,
    on_retry: Any = None,
) -> StageResult:
    """Run a stage through the selected provider and return normalized output and usage."""
    validate_provider(config)
    if config.ai_provider == "gemini":
        from app.research import generate_gemini_stage

        retry_options = {"on_retry": on_retry} if on_retry else {}
        return await generate_gemini_stage(
            stage.name, stage.instructions, prompt, timeout_seconds=timeout_seconds, config=config,
            **retry_options,
        )

    try:
        from agents import ModelSettings, RunConfig, Runner
    except ImportError as exc:
        raise ProviderConfigurationError(
            "OpenAI support is unavailable; install the backend openai extra"
        ) from exc
    run_config = None
    if timeout_seconds is not None:
        run_config = RunConfig(model_settings=ModelSettings(timeout=float(timeout_seconds)))
    run = await Runner.run(stage.provider_agent, prompt, run_config=run_config)
    usage = run.context_wrapper.usage
    return StageResult(
        final_output=str(run.final_output),
        input_tokens=int(usage.input_tokens or 0),
        output_tokens=int(usage.output_tokens or 0),
        cached_input_tokens=int(
            getattr(getattr(usage, "input_tokens_details", None), "cached_tokens", 0) or 0
        ),
        sources=tuple(_openai_sources(run)),
    )


async def run_custom_gemini_agent(
    *,
    name: str,
    instructions: str,
    prompt: str,
    model: str,
    temperature: float,
    max_output_tokens: int,
    timeout_seconds: int,
    config: Settings = settings,
    on_retry: Any = None,
) -> StageResult:
    """Execute a saved Agent Studio configuration through Gemini only.

    Saved OpenAI configurations remain editable, but are intentionally not executable
    until their SDK settings and limits have dedicated verification coverage.
    """
    if not config.gemini_api_key:
        raise ProviderConfigurationError("Gemini API key is not configured")
    if not model.startswith("gemini-") or model != config.gemini_model:
        raise ProviderConfigurationError("The saved Gemini model is unsupported")
    if len(prompt) + len(instructions) > config.max_stage_input_chars:
        raise ProviderConfigurationError("Custom agent input exceeded the configured limit")
    from app.research import generate_gemini_stage

    return await generate_gemini_stage(
        name,
        instructions,
        prompt,
        timeout_seconds=timeout_seconds,
        config=config,
        on_retry=on_retry,
        model=model,
        temperature=temperature,
        max_output_tokens=max_output_tokens,
    )


def _openai_sources(run: Any) -> list[dict[str, str]]:
    found: dict[str, dict[str, str]] = {}
    for response in getattr(run, "raw_responses", []):
        for item in getattr(response, "output", []):
            for content in getattr(item, "content", []):
                for annotation in getattr(content, "annotations", []):
                    citation = getattr(annotation, "url_citation", annotation)
                    url = getattr(citation, "url", None)
                    if url and url.startswith(("https://", "http://")):
                        found[url] = {"url": url, "title": getattr(citation, "title", None) or url}
    return list(found.values())
