"""Saved ordered custom-agent workflows, separate from the fixed five stages."""

import asyncio
import math
import time
from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app import database
from app.config import settings
from app.custom_workflow_schemas import (
    WorkflowDefinitionInput,
    WorkflowDefinitionRead,
    WorkflowRunInput,
    WorkflowRunRead,
)
from app.database import (
    CustomAgent,
    CustomWorkflow,
    CustomWorkflowRun,
    CustomWorkflowStep,
    CustomWorkflowStepRun,
)
from app.providers import ProviderConfigurationError, ProviderRequestError, run_custom_gemini_agent

router = APIRouter(prefix="/api/custom-workflows", tags=["custom-workflows"])


def _definition(row: CustomWorkflow) -> WorkflowDefinitionRead:
    return WorkflowDefinitionRead(id=row.id, name=row.name, description=row.description,
        enabled=row.enabled, agent_ids=[item.agent_id for item in row.steps],
        created_at=row.created_at, updated_at=row.updated_at)


def _run_read(row: CustomWorkflowRun) -> WorkflowRunRead:
    return WorkflowRunRead.model_validate(row)


def _get(session, workflow_id: UUID) -> CustomWorkflow:
    row = session.scalar(select(CustomWorkflow).options(selectinload(CustomWorkflow.steps))
        .where(CustomWorkflow.id == workflow_id))
    if row is None:
        raise HTTPException(status_code=404, detail="Custom workflow not found")
    return row


def _validate_agents(session, ids: list[UUID]) -> None:
    agents = session.scalars(select(CustomAgent).where(CustomAgent.id.in_(ids))).all()
    if len(agents) != len(ids):
        raise HTTPException(status_code=422, detail="One or more custom agents do not exist")
    if any(not agent.enabled or agent.provider != "gemini" or agent.model != settings.gemini_model for agent in agents):
        raise HTTPException(status_code=422, detail="Workflow agents must be enabled and use the configured Gemini model")


def _snapshot(session, workflow_id: UUID):
    workflow = _get(session, workflow_id)
    if not workflow.enabled:
        raise HTTPException(status_code=409, detail="This workflow is disabled")
    agents = []
    for step in workflow.steps:
        agent = session.get(CustomAgent, step.agent_id)
        if agent is None or not agent.enabled or agent.provider != "gemini" or agent.model != settings.gemini_model:
            raise HTTPException(status_code=409, detail="A workflow agent is missing, disabled, or unsupported")
        agents.append({
            "name": agent.name,
            "instructions": agent.system_instructions,
            "model": agent.model,
            "temperature": agent.temperature,
            "max_output_tokens": agent.max_output_tokens,
            "provider": agent.provider,
        })
    return workflow.name, agents


@router.get("", response_model=list[WorkflowDefinitionRead])
def list_definitions() -> list[WorkflowDefinitionRead]:
    with database.SessionLocal() as session:
        rows = session.scalars(select(CustomWorkflow).options(selectinload(CustomWorkflow.steps))
            .order_by(CustomWorkflow.created_at.desc())).all()
        return [_definition(row) for row in rows]


@router.post("", response_model=WorkflowDefinitionRead, status_code=201)
def create_definition(body: WorkflowDefinitionInput) -> WorkflowDefinitionRead:
    with database.SessionLocal.begin() as session:
        _validate_agents(session, body.agent_ids)
        row = CustomWorkflow(name=body.name, description=body.description, enabled=body.enabled)
        row.steps = [CustomWorkflowStep(position=i, agent_id=agent_id) for i, agent_id in enumerate(body.agent_ids)]
        session.add(row)
        session.flush()
        return _definition(row)


@router.get("/{workflow_id}", response_model=WorkflowDefinitionRead)
def get_definition(workflow_id: UUID) -> WorkflowDefinitionRead:
    with database.SessionLocal() as session:
        return _definition(_get(session, workflow_id))


@router.put("/{workflow_id}", response_model=WorkflowDefinitionRead)
def update_definition(workflow_id: UUID, body: WorkflowDefinitionInput) -> WorkflowDefinitionRead:
    with database.SessionLocal.begin() as session:
        row = _get(session, workflow_id)
        _validate_agents(session, body.agent_ids)
        row.name, row.description, row.enabled = body.name, body.description, body.enabled
        row.updated_at = datetime.now(UTC)
        row.steps.clear()
        session.flush()
        row.steps.extend(CustomWorkflowStep(position=i, agent_id=agent_id) for i, agent_id in enumerate(body.agent_ids))
        session.flush()
        return _definition(row)


@router.delete("/{workflow_id}", status_code=204)
def delete_definition(workflow_id: UUID) -> None:
    with database.SessionLocal.begin() as session:
        row = _get(session, workflow_id)
        session.delete(row)


@router.get("/runs/{run_id}", response_model=WorkflowRunRead)
def get_run(run_id: UUID) -> WorkflowRunRead:
    with database.SessionLocal() as session:
        row = session.scalar(select(CustomWorkflowRun).options(selectinload(CustomWorkflowRun.steps))
            .where(CustomWorkflowRun.id == run_id))
        if row is None:
            raise HTTPException(status_code=404, detail="Custom workflow run not found")
        return _run_read(row)


@router.get("/{workflow_id}/runs", response_model=list[WorkflowRunRead])
def list_runs(workflow_id: UUID) -> list[WorkflowRunRead]:
    with database.SessionLocal() as session:
        _get(session, workflow_id)
        rows = session.scalars(select(CustomWorkflowRun).options(selectinload(CustomWorkflowRun.steps))
            .where(CustomWorkflowRun.workflow_id == workflow_id)
            .order_by(CustomWorkflowRun.created_at.desc()).limit(30)).all()
        return [_run_read(row) for row in rows]


def _save_step(run_id: UUID, position: int, **fields) -> None:
    with database.SessionLocal.begin() as session:
        row = session.scalar(select(CustomWorkflowStepRun).where(
            CustomWorkflowStepRun.run_id == run_id, CustomWorkflowStepRun.position == position))
        if row is None:
            raise RuntimeError("Workflow step record missing")
        for field, value in fields.items():
            setattr(row, field, value)


def _finish_run(run_id: UUID, status: str, *, result: str | None = None, error: str | None = None) -> WorkflowRunRead:
    with database.SessionLocal.begin() as session:
        row = session.scalar(select(CustomWorkflowRun).options(selectinload(CustomWorkflowRun.steps))
            .where(CustomWorkflowRun.id == run_id))
        if row is None:
            raise RuntimeError("Workflow run record missing")
        row.status = status
        row.result = result
        row.error = error
        row.completed_at = datetime.now(UTC)
        session.flush()
        return _run_read(row)


async def _execute(run_id: UUID, task: str, agents: list[dict]) -> WorkflowRunRead:
    last_output = ""
    for position, agent in enumerate(agents):
        # The next step receives only the original task and previous step output,
        # avoiding uncontrolled accumulation of all prior outputs.
        prompt = task if position == 0 else f"Original task:\n{task}\n\nPrevious agent output:\n{last_output}"
        if (len(prompt) + len(agent["instructions"]) > settings.max_stage_input_chars or
                math.ceil((len(prompt) + len(agent["instructions"])) / 4) > settings.custom_agent_max_input_tokens):
            message = "Workflow step input exceeds configured limit"
            _save_step(run_id, position, status="failed", error=message)
            return _finish_run(run_id, "failed", result=last_output or None, error=message)
        _save_step(run_id, position, status="running")
        started = time.monotonic()
        try:
            result = await asyncio.wait_for(run_custom_gemini_agent(
                name=agent["name"], instructions=agent["instructions"], prompt=prompt,
                model=agent["model"], temperature=agent["temperature"],
                max_output_tokens=agent["max_output_tokens"],
                timeout_seconds=settings.custom_agent_timeout_seconds, config=settings,
            ), timeout=settings.custom_agent_timeout_seconds)
            elapsed = int((time.monotonic() - started) * 1000)
            if result.output_tokens > agent["max_output_tokens"]:
                raise ValueError("Provider output exceeds the configured token limit")
            if len(result.final_output) > settings.max_stage_output_chars:
                raise ValueError("Provider output exceeds the configured character limit")
            last_output = result.final_output
            _save_step(run_id, position, status="completed", output=last_output,
                elapsed_ms=elapsed, input_tokens=result.input_tokens,
                output_tokens=result.output_tokens)
        except asyncio.CancelledError:
            _save_step(run_id, position, status="cancelled",
                elapsed_ms=int((time.monotonic() - started) * 1000), error="Execution cancelled")
            _finish_run(run_id, "cancelled", result=last_output or None, error="Execution cancelled")
            raise
        except TimeoutError:
            message = f"Agent step exceeded its {settings.custom_agent_timeout_seconds}s timeout"
            _save_step(run_id, position, status="timed_out", error=message,
                elapsed_ms=int((time.monotonic() - started) * 1000))
            return _finish_run(run_id, "timed_out", result=last_output or None, error=message)
        except (ProviderConfigurationError, ProviderRequestError, ValueError):
            # Do not expose provider raw exceptions, which might contain credentials.
            message = "Provider failed or returned invalid output; check server logs and provider availability"
            _save_step(run_id, position, status="failed", error=message,
                elapsed_ms=int((time.monotonic() - started) * 1000))
            return _finish_run(run_id, "failed", result=last_output or None, error=message)
        except Exception:  # noqa: BLE001 - SDK errors must not expose sensitive provider details.
            message = "Agent execution failed"
            _save_step(run_id, position, status="failed", error=message,
                elapsed_ms=int((time.monotonic() - started) * 1000))
            return _finish_run(run_id, "failed", result=last_output or None, error=message)
    return _finish_run(run_id, "completed", result=last_output)

@router.post("/{workflow_id}/execute", response_model=WorkflowRunRead)
async def execute_definition(workflow_id: UUID, body: WorkflowRunInput) -> WorkflowRunRead:
    with database.SessionLocal.begin() as session:
        name, agents = _snapshot(session, workflow_id)
        run = CustomWorkflowRun(workflow_id=workflow_id, workflow_name=name, task=body.task)
        run.steps = [CustomWorkflowStepRun(position=i, agent_name=agent["name"],
            provider=agent["provider"], model=agent["model"], status="pending")
            for i, agent in enumerate(agents)]
        session.add(run)
        session.flush()
        run_id = run.id
    return await _execute(run_id, body.task, agents)
