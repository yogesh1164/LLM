"""Definitions for the five provider-independent workflow stages."""

from app.config import settings
from app.providers import AgentStage, build_agent


def build_agents(sources: list[dict] | None = None, grounding_usage: dict | None = None) -> dict[str, AgentStage]:
    """Build stage definitions; Gemini research uses native grounding at run time."""
    del sources, grounding_usage  # Retain the call signature used by workflow integrations.
    research_tools = []
    if settings.ai_provider == "openai" and settings.openai_web_search_enabled:
        try:
            from agents import WebSearchTool
        except ImportError as exc:
            from app.providers import ProviderConfigurationError

            raise ProviderConfigurationError(
                "OpenAI support is unavailable; install the backend openai extra"
            ) from exc
        research_tools = [WebSearchTool(search_context_size="medium", external_web_access=True)]

    return {
        "orchestrator": build_agent(
            "Orchestrator Agent",
            "Create a concise execution plan for the user task. Identify the key question, useful research angles, and uncertainty to check.",
        ),
        "research": build_agent(
            "Research Agent",
            "Research the user's task. Base factual claims on retrieved evidence, distinguish evidence from uncertainty, and never invent source URLs.",
            tools=research_tools,
        ),
        "analysis": build_agent(
            "Analysis Agent",
            "Analyze the supplied research notes. Identify implications and uncertainties; do not invent facts.",
        ),
        "report": build_agent(
            "Report Agent",
            "Turn the supplied analysis into a clear, structured, actionable report. Preserve uncertainty.",
        ),
        "review": build_agent(
            "Review Agent",
            "Review the report for unsupported claims, clarity, and completeness. Return the corrected final report.",
        ),
    }
