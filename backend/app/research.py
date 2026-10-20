"""Gemini direct SDK calls and native Google Search grounding extraction."""

import asyncio
import logging
import random
import time
from typing import Any

from app.config import Settings, settings

logger = logging.getLogger(__name__)


def extract_grounding_sources(response: object) -> list[dict[str, str]]:
    sources: list[dict[str, str]] = []
    for candidate in getattr(response, "candidates", None) or []:
        metadata = getattr(candidate, "grounding_metadata", None)
        for chunk in getattr(metadata, "grounding_chunks", None) or []:
            web = getattr(chunk, "web", None)
            uri = getattr(web, "uri", None)
            title = getattr(web, "title", None)
            if uri:
                _add_source(sources, uri, title)
    for step in getattr(response, "steps", None) or []:
        for content in getattr(step, "content", None) or []:
            for annotation in getattr(content, "annotations", None) or []:
                if getattr(annotation, "type", None) == "url_citation":
                    _add_source(
                        sources,
                        getattr(annotation, "url", None),
                        getattr(annotation, "title", None),
                    )
    return sources


def _add_source(sources: list[dict[str, str]], url: str | None, title: str | None) -> None:
    if url and url.startswith(("https://", "http://")):
        source = {"url": url, "title": title or url}
        if source not in sources:
            sources.append(source)


async def generate_gemini_stage(
    stage_name: str,
    instructions: str,
    prompt: str,
    *,
    timeout_seconds: int | None = None,
    config: Settings = settings,
    on_retry: Any = None,
    model: str | None = None,
    temperature: float | None = None,
    max_output_tokens: int | None = None,
) -> Any:
    """Run one Gemini stage using google-genai; ground Research only when opted in."""
    if not config.gemini_api_key:
        raise ValueError("Gemini API key is not configured")
    request_timeout = timeout_seconds or config.agent_timeout_seconds
    deadline = time.monotonic() + request_timeout

    def generate(timeout: float) -> tuple[str, int, int, list[dict[str, str]]]:
        from google import genai

        client = genai.Client(
            api_key=config.gemini_api_key.get_secret_value(),
            http_options={
                "timeout": max(1, int(timeout * 1000)),
                "retry_options": {"attempts": 1},
            },
        )
        tools = None
        if stage_name.lower() == "research" and config.gemini_search_grounding_enabled:
            tools = [{"type": "google_search"}]
        try:
            request_options: dict[str, Any] = {
                "model": model or config.gemini_model,
                "input": prompt,
                "system_instruction": instructions,
                "tools": tools,
            }
            if temperature is not None or max_output_tokens is not None:
                request_options["generation_config"] = {
                    **({"temperature": temperature} if temperature is not None else {}),
                    **({"max_output_tokens": max_output_tokens} if max_output_tokens is not None else {}),
                }
            api_started = time.monotonic()
            try:
                response = client.interactions.create(**request_options)
            finally:
                logger.info(
                    "Gemini SDK request finished: stage=%s duration_seconds=%.2f",
                    stage_name,
                    time.monotonic() - api_started,
                )
        finally:
            client.close()
        usage = getattr(response, "usage", None)
        return (
            getattr(response, "output_text", None) or "",
            int(getattr(usage, "total_input_tokens", 0) or 0),
            int(getattr(usage, "total_output_tokens", 0) or 0),
            extract_grounding_sources(response) if tools else [],
        )

    attempt = 0
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("Gemini request exceeded the remaining stage timeout")
        logger.info("Gemini request attempt: stage=%s attempt=%d", stage_name, attempt + 1)
        try:
            output, input_tokens, output_tokens, sources = await asyncio.wait_for(
                asyncio.to_thread(generate, remaining), timeout=remaining
            )
            break
        except TimeoutError:
            raise
        except Exception as exc:
            status = getattr(exc, "status_code", None) or getattr(exc, "code", None)
            message = str(exc)
            lowered = message.lower()
            quota_429 = any(term in lowered for term in (
                "quota", "billing", "daily limit", "per day", "resource_exhausted",
            ))
            transient_429 = status == 429 and not quota_429 and any(
                term in lowered for term in ("rate limit", "too many requests", "try again", "retry")
            )
            retryable = status == 503 or transient_429
            if not retryable or attempt >= config.provider_retry_attempts:
                from app.providers import ProviderRequestError

                raise ProviderRequestError(status, message.replace(
                    config.gemini_api_key.get_secret_value(), "[redacted]"
                )) from exc
            delay_cap = min(config.provider_retry_max_delay_seconds,
                            config.provider_retry_base_delay_seconds * (2 ** attempt))
            delay = random.uniform(0, delay_cap)
            if deadline - time.monotonic() <= delay:
                from app.providers import ProviderRequestError

                raise ProviderRequestError(status, message.replace(
                    config.gemini_api_key.get_secret_value(), "[redacted]"
                )) from exc
            attempt += 1
            if on_retry:
                await on_retry({"attempt": attempt, "max_attempts": config.provider_retry_attempts,
                                "delay_seconds": round(delay, 2), "status_code": status})
            logger.warning(
                "Gemini transient error: stage=%s status=%s retry=%d delay_seconds=%.2f",
                stage_name, status, attempt, delay,
            )
            await asyncio.sleep(delay)
    from app.providers import StageResult

    return StageResult(
        final_output=output,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        sources=tuple(sources),
    )


async def google_search_grounded(query: str) -> dict:
    """Compatibility helper returning Gemini-grounded research output and citations."""
    result = await generate_gemini_stage(
        "Research",
        "Answer using Google Search grounding. Return only URLs present in grounding metadata.",
        query,
    )
    return {
        "answer": result.final_output,
        "sources": list(result.sources),
        "input_tokens": result.input_tokens,
        "output_tokens": result.output_tokens,
    }
