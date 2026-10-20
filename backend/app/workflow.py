"""Orchestrates the five sequential workflow stages with bounded execution."""

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import Any

from app.agents import build_agents
from app.config import settings
from app.database import fail_stage, finish_stage, start_stage, update_task
from app.providers import run_agent_stage
from app.schemas import SourceReference, WorkflowResponse

Progress = Callable[[dict[str, Any]], Awaitable[None]]


class StageTimeoutError(TimeoutError):
    """A single agent exceeded its configured execution limit."""


class WorkflowTimeoutError(TimeoutError):
    """The workflow exhausted its total execution budget."""


async def run_workflow(task: str, task_id: str, progress: Progress | None = None) -> dict[str, Any]:
    workflow_started = time.monotonic()
    agents = build_agents()
    total_input = total_output = cached_input = calls = 0
    sources: list[SourceReference] = []
    outputs: dict[str, str] = {}

    def save_partial() -> None:
        partial = {**outputs, "sources": [source.model_dump(mode="json") for source in sources],
                   "input_tokens": total_input, "output_tokens": total_output,
                   "total_tokens": total_input + total_output}
        update_task(task_id, status="running", result=partial, total_tokens=total_input + total_output)

    async def stage(name: str, prompt: str) -> str:
        nonlocal total_input, total_output, cached_input, calls
        stage_name = "Orchestrator" if name == "orchestrator" else name.title()
        configured_timeout = getattr(settings, f"{name}_timeout_seconds", None)
        stage_timeout = configured_timeout or settings.agent_timeout_seconds
        remaining_total = settings.workflow_timeout_seconds - (time.monotonic() - workflow_started)
        total_budget_limits_stage = remaining_total <= stage_timeout
        effective_timeout = min(stage_timeout, max(0.001, remaining_total))
        stage_id = start_stage(task_id, stage_name)
        started = time.monotonic()
        if progress:
            await progress({"type": "stage", "agent": stage_name, "status": "running"})
        try:
            if len(prompt) > settings.max_stage_input_chars:
                raise RuntimeError(
                    f"{stage_name} input exceeded the configured "
                    f"{settings.max_stage_input_chars}-character limit"
                )
            if calls >= settings.max_model_calls_per_workflow:
                raise RuntimeError("Workflow reached the configured model call limit")
            calls += 1
            async def retry_progress(info: dict[str, Any]) -> None:
                if progress:
                    await progress({"type": "stage_retry", "agent": stage_name, **info})
            try:
                run = await asyncio.wait_for(
                    run_agent_stage(agents[name], prompt,
                                    timeout_seconds=effective_timeout, on_retry=retry_progress),
                    timeout=effective_timeout,
                )
            except TimeoutError as exc:
                if total_budget_limits_stage:
                    raise WorkflowTimeoutError(
                        f"Workflow exceeded its {settings.workflow_timeout_seconds}s total timeout"
                    ) from exc
                raise StageTimeoutError(
                    f"{stage_name} exceeded its {stage_timeout}s timeout"
                ) from exc
            elapsed_ms = int((time.monotonic() - started) * 1000)
            total_input += run.input_tokens
            total_output += run.output_tokens
            cached_input += run.cached_input_tokens
            output = run.final_output[:settings.max_stage_output_chars]
            if name == "research":
                sources.extend(SourceReference(**source) for source in run.sources)
            outputs["plan" if name == "orchestrator" else name] = output
            finish_stage(stage_id, output=output, input_tokens=run.input_tokens,
                         output_tokens=run.output_tokens, elapsed_ms=elapsed_ms)
            save_partial()
            if progress:
                await progress({"type": "stage", "agent": stage_name, "status": "completed",
                                "output": output, "elapsed_ms": elapsed_ms})
            return output
        except asyncio.CancelledError:
            elapsed_ms = int((time.monotonic() - started) * 1000)
            total_timeout = time.monotonic() - workflow_started >= settings.workflow_timeout_seconds
            status = "timed_out" if total_timeout else "cancelled"
            reason = (f"Workflow exceeded its {settings.workflow_timeout_seconds}s total timeout"
                      if total_timeout else "Stage cancelled because the workflow was cancelled")
            fail_stage(stage_id, reason, status=status, elapsed_ms=elapsed_ms)
            if progress:
                await progress({"type": "stage", "agent": stage_name, "status": status,
                                "error": reason if total_timeout else None, "elapsed_ms": elapsed_ms})
            raise
        except BaseException as exc:
            elapsed_ms = int((time.monotonic() - started) * 1000)
            timed_out = isinstance(exc, (StageTimeoutError, WorkflowTimeoutError))
            fail_stage(stage_id, str(exc) or "Agent stage failed",
                       status="timed_out" if timed_out else "failed", elapsed_ms=elapsed_ms)
            if progress:
                await progress({"type": "stage", "agent": stage_name,
                                "status": "timed_out" if timed_out else "failed",
                                "error": str(exc) or "Agent stage failed", "elapsed_ms": elapsed_ms})
            raise

    started = workflow_started
    try:
        if progress:
            await progress({"type": "workflow", "status": "running"})
        plan = await stage("orchestrator", task)
        research = await stage("research", f"User task: {task}\n\nExecution plan:\n{plan}")
        analysis = await stage("analysis", f"User task: {task}\n\nExecution plan:\n{plan}\n\nResearch notes:\n{research}")
        report = await stage("report", f"User task: {task}\n\nAnalysis:\n{analysis}")
        review = await stage("review", f"User task: {task}\n\nDraft report:\n{report}")
        cost = (max(0, total_input - cached_input) * settings.input_token_cost_per_million
                + cached_input * settings.cached_input_token_cost_per_million
                + total_output * settings.output_token_cost_per_million) / 1_000_000
        if settings.ai_provider == "gemini":
            cost = None
        result = {"research": research, "analysis": analysis, "report": report, "review": review,
                  "sources": sources, "input_tokens": total_input, "output_tokens": total_output,
                  "total_tokens": total_input + total_output, "estimated_cost": cost,
                  "provider": settings.ai_provider, "model": settings.active_model,
                  "elapsed_ms": int((time.monotonic() - started) * 1000)}
        if progress:
            await progress({"type": "workflow", "status": "completed", "elapsed_ms": result["elapsed_ms"],
                            "total_tokens": total_input + total_output, "estimated_cost": cost,
                            "sources": [s.model_dump(mode="json") for s in sources]})
        return result
    except asyncio.CancelledError:
        total_timeout = time.monotonic() - started >= settings.workflow_timeout_seconds
        if progress:
            await progress({"type": "workflow", "status": "timed_out" if total_timeout else "cancelled",
                            "error": (f"Workflow exceeded its {settings.workflow_timeout_seconds}s total timeout"
                                      if total_timeout else None),
                            "elapsed_ms": int((time.monotonic() - started) * 1000)})
        raise
    except BaseException as exc:
        if progress:
            timed_out = isinstance(exc, (StageTimeoutError, WorkflowTimeoutError))
            await progress({"type": "workflow", "status": "timed_out" if timed_out else "failed",
                            "error": str(exc), "elapsed_ms": int((time.monotonic() - started) * 1000)})
        raise


async def run_collaboration(task: str, task_id: str) -> WorkflowResponse:
    """Legacy response contract backed by the same orchestrated workflow."""
    result = await run_workflow(task, task_id)
    return WorkflowResponse(research=result["research"], analysis=result["analysis"])
