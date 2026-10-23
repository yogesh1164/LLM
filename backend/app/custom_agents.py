"""CRUD and isolated execution API for Agent Studio custom agents."""

import asyncio
import math
import time
from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app import database
from app.config import settings
from app.custom_agent_schemas import (
    AgentConfigCreate,
    AgentConfigPatch,
    AgentConfigRead,
    AgentOptionsResponse,
    CustomAgentExecutionRead,
    CustomAgentExecutionRequest,
    ProviderOption,
    configured_models,
)
from app.database import CustomAgent, CustomAgentExecution
from app.provider_capacity import ProviderBusyError
from app.providers import ProviderConfigurationError, ProviderRequestError, run_custom_gemini_agent

router = APIRouter(prefix="/api/agents", tags=["agent-studio"])
BUILT_IN_NAMES = {"orchestrator", "research", "analysis", "report", "review"}


def _protect_builtin_identifier(agent_id: str) -> UUID:
    normalized = agent_id.lower().replace("builtin:", "").replace("_", " ").strip()
    if normalized in BUILT_IN_NAMES:
        raise HTTPException(status_code=403, detail="Built-in workflow agents are protected and cannot be edited here")
    try:
        return UUID(agent_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Custom agent not found") from None


def _get_agent(session, agent_id: str) -> CustomAgent:
    identifier = _protect_builtin_identifier(agent_id)
    agent = session.get(CustomAgent, identifier)
    if agent is None:
        raise HTTPException(status_code=404, detail="Custom agent not found")
    return agent


def _check_reserved_name(name: str) -> None:
    if name.casefold() in BUILT_IN_NAMES:
        raise HTTPException(status_code=409, detail="That name is reserved for a built-in workflow agent")


def _check_unique_name(session, name: str, exclude: UUID | None = None) -> None:
    query = select(CustomAgent.id).where(func.lower(CustomAgent.name) == name.lower())
    if exclude is not None:
        query = query.where(CustomAgent.id != exclude)
    if session.scalar(query) is not None:
        raise HTTPException(status_code=409, detail="An agent with that name already exists")


def _read(agent: CustomAgent) -> AgentConfigRead:
    return AgentConfigRead.model_validate(agent)


def _read_execution(execution: CustomAgentExecution) -> CustomAgentExecutionRead:
    return CustomAgentExecutionRead.model_validate(execution)


def _start_execution(agent: CustomAgent, task: str) -> UUID:
    with database.SessionLocal.begin() as session:
        execution = CustomAgentExecution(
            agent_id=agent.id,
            task=task,
            status="running",
            provider=agent.provider,
            model=agent.model,
        )
        session.add(execution)
        session.flush()
        return execution.id


def _finish_execution(execution_id: UUID, *, status_value: str, elapsed_ms: int,
                      result: str | None = None, error: str | None = None,
                      input_tokens: int | None = None, output_tokens: int | None = None) -> CustomAgentExecutionRead:
    with database.SessionLocal.begin() as session:
        execution = session.get(CustomAgentExecution, execution_id)
        if execution is None:
            raise RuntimeError("Custom agent execution record was not found")
        execution.status = status_value
        execution.elapsed_ms = elapsed_ms
        execution.completed_at = datetime.now(UTC)
        execution.result = result
        execution.error = error
        execution.input_tokens = input_tokens
        execution.output_tokens = output_tokens
        session.flush()
        return _read_execution(execution)


async def _execute_saved_agent(agent: CustomAgent, task: str) -> CustomAgentExecutionRead:
    try:
        validated = AgentConfigCreate.model_validate({
            field: getattr(agent, field) for field in AgentConfigCreate.model_fields
        })
    except ValidationError as exc:
        message = "; ".join(error["msg"] for error in exc.errors())
        raise HTTPException(status_code=422, detail=f"Saved agent configuration is invalid: {message}") from None
    if not validated.enabled:
        raise HTTPException(status_code=409, detail="This custom agent is disabled")
    if validated.provider != "gemini":
        raise HTTPException(
            status_code=422,
            detail="Custom agent execution currently supports Gemini configurations only",
        )
    estimated_input_tokens = math.ceil((len(task) + len(validated.system_instructions)) / 4)
    if estimated_input_tokens > settings.custom_agent_max_input_tokens:
        raise HTTPException(status_code=422, detail="Custom agent input exceeds the configured token limit")

    execution_id = _start_execution(agent, task)
    started = time.monotonic()
    try:
        result = await asyncio.wait_for(
            run_custom_gemini_agent(
                name=validated.name,
                instructions=validated.system_instructions,
                prompt=task,
                model=validated.model,
                temperature=validated.temperature,
                max_output_tokens=validated.max_output_tokens,
                timeout_seconds=settings.custom_agent_timeout_seconds,
                config=settings,
            ),
            timeout=settings.custom_agent_timeout_seconds,
        )
        elapsed_ms = int((time.monotonic() - started) * 1000)
        if result.output_tokens > validated.max_output_tokens:
            message = "Provider output exceeded the saved output-token limit"
            _finish_execution(execution_id, status_value="failed", elapsed_ms=elapsed_ms, error=message,
                              input_tokens=result.input_tokens, output_tokens=result.output_tokens)
            raise HTTPException(status_code=502, detail=message)
        return _finish_execution(
            execution_id,
            status_value="completed",
            elapsed_ms=elapsed_ms,
            result=result.final_output[:settings.max_stage_output_chars],
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
        )
    except HTTPException:
        raise
    except asyncio.CancelledError:
        _finish_execution(execution_id, status_value="cancelled",
                          elapsed_ms=int((time.monotonic() - started) * 1000),
                          error="Execution cancelled")
        raise
    except ProviderBusyError:
        message = "AI workers are busy; try again shortly"
        _finish_execution(execution_id, status_value="failed",
                          elapsed_ms=int((time.monotonic() - started) * 1000), error=message)
        raise HTTPException(status_code=503, detail=message,
                            headers={"Retry-After": "5"}) from None
    except TimeoutError:
        elapsed_ms = int((time.monotonic() - started) * 1000)
        message = f"Custom agent exceeded its {settings.custom_agent_timeout_seconds}s timeout"
        _finish_execution(execution_id, status_value="timed_out", elapsed_ms=elapsed_ms, error=message)
        raise HTTPException(status_code=504, detail=message) from None
    except ProviderConfigurationError as exc:
        elapsed_ms = int((time.monotonic() - started) * 1000)
        message = str(exc)
        _finish_execution(execution_id, status_value="failed", elapsed_ms=elapsed_ms, error=message)
        raise HTTPException(status_code=503, detail=message) from None
    except ProviderRequestError:
        elapsed_ms = int((time.monotonic() - started) * 1000)
        message = "Gemini request failed. Check provider availability and try again."
        _finish_execution(execution_id, status_value="failed", elapsed_ms=elapsed_ms, error=message)
        raise HTTPException(status_code=502, detail=message) from None
    except Exception:  # noqa: BLE001 - provider implementations can raise SDK-specific errors.
        elapsed_ms = int((time.monotonic() - started) * 1000)
        message = "Custom agent execution failed. Check the saved configuration and try again."
        _finish_execution(execution_id, status_value="failed", elapsed_ms=elapsed_ms, error=message)
        raise HTTPException(status_code=502, detail=message) from None


@router.get("/options", response_model=AgentOptionsResponse)
def agent_options() -> AgentOptionsResponse:
    return AgentOptionsResponse(providers=[
        ProviderOption(provider="gemini", models=configured_models("gemini")),
        ProviderOption(provider="openai", models=configured_models("openai")),
    ])


@router.get("/{agent_id}/executions", response_model=list[CustomAgentExecutionRead])
def list_agent_executions(agent_id: str) -> list[CustomAgentExecutionRead]:
    with database.SessionLocal() as session:
        agent = _get_agent(session, agent_id)
        executions = session.scalars(
            select(CustomAgentExecution)
            .where(CustomAgentExecution.agent_id == agent.id)
            .order_by(CustomAgentExecution.created_at.desc())
            .limit(50)
        ).all()
        return [_read_execution(execution) for execution in executions]


@router.post("/{agent_id}/execute", response_model=CustomAgentExecutionRead)
async def execute_agent(agent_id: str, request: CustomAgentExecutionRequest) -> CustomAgentExecutionRead:
    with database.SessionLocal() as session:
        agent = _get_agent(session, agent_id)
    return await _execute_saved_agent(agent, request.task)


@router.get("", response_model=list[AgentConfigRead])
def list_agents() -> list[AgentConfigRead]:
    with database.SessionLocal() as session:
        agents = session.scalars(select(CustomAgent).order_by(func.lower(CustomAgent.name))).all()
        return [_read(agent) for agent in agents]


@router.get("/{agent_id}", response_model=AgentConfigRead)
def get_agent(agent_id: str) -> AgentConfigRead:
    with database.SessionLocal() as session:
        return _read(_get_agent(session, agent_id))


@router.post("", response_model=AgentConfigRead, status_code=status.HTTP_201_CREATED)
def create_agent(request: AgentConfigCreate) -> AgentConfigRead:
    _check_reserved_name(request.name)
    agent = CustomAgent(**request.model_dump())
    try:
        with database.SessionLocal.begin() as session:
            _check_unique_name(session, request.name)
            session.add(agent)
            session.flush()
    except IntegrityError:
        raise HTTPException(status_code=409, detail="An agent with that name already exists") from None
    return _read(agent)


@router.patch("/{agent_id}", response_model=AgentConfigRead)
def update_agent(agent_id: str, request: AgentConfigPatch) -> AgentConfigRead:
    identifier = _protect_builtin_identifier(agent_id)
    try:
        with database.SessionLocal.begin() as session:
            agent = session.get(CustomAgent, identifier)
            if agent is None:
                raise HTTPException(status_code=404, detail="Custom agent not found")
            merged = {field: getattr(agent, field) for field in AgentConfigCreate.model_fields}
            merged.update(request.model_dump(exclude_unset=True))
            try:
                validated = AgentConfigCreate.model_validate(merged)
            except ValidationError as exc:
                message = "; ".join(error["msg"] for error in exc.errors())
                raise HTTPException(status_code=422, detail=message) from None
            _check_reserved_name(validated.name)
            _check_unique_name(session, validated.name, exclude=identifier)
            for field, value in validated.model_dump().items():
                setattr(agent, field, value)
            session.flush()
    except IntegrityError:
        raise HTTPException(status_code=409, detail="An agent with that name already exists") from None
    return _read(agent)


@router.post("/{agent_id}/duplicate", response_model=AgentConfigRead, status_code=status.HTTP_201_CREATED)
def duplicate_agent(agent_id: str) -> AgentConfigRead:
    identifier = _protect_builtin_identifier(agent_id)
    try:
        with database.SessionLocal.begin() as session:
            source = session.get(CustomAgent, identifier)
            if source is None:
                raise HTTPException(status_code=404, detail="Custom agent not found")
            base_name = source.name[:68].rstrip() + " (Copy)"
            candidate = base_name
            suffix = 2
            while session.scalar(select(CustomAgent.id).where(func.lower(CustomAgent.name) == candidate.lower())):
                suffix_text = f" (Copy {suffix})"
                candidate = source.name[: 80 - len(suffix_text)].rstrip() + suffix_text
                suffix += 1
            duplicate = CustomAgent(
                name=candidate,
                description=source.description,
                role=source.role,
                system_instructions=source.system_instructions,
                provider=source.provider,
                model=source.model,
                temperature=source.temperature,
                max_output_tokens=source.max_output_tokens,
                enabled=source.enabled,
            )
            session.add(duplicate)
            session.flush()
    except IntegrityError:
        raise HTTPException(status_code=409, detail="Could not create a uniquely named agent copy") from None
    return _read(duplicate)


@router.delete("/{agent_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_agent(agent_id: str) -> None:
    identifier = _protect_builtin_identifier(agent_id)
    with database.SessionLocal.begin() as session:
        agent = session.get(CustomAgent, identifier)
        if agent is None:
            raise HTTPException(status_code=404, detail="Custom agent not found")
        session.delete(agent)
