"""CRUD API for Agent Studio configuration; never used by workflow execution."""

from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app import database
from app.custom_agent_schemas import (
    AgentConfigCreate,
    AgentConfigPatch,
    AgentConfigRead,
    AgentOptionsResponse,
    ProviderOption,
    configured_models,
)
from app.database import CustomAgent

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


@router.get("/options", response_model=AgentOptionsResponse)
def agent_options() -> AgentOptionsResponse:
    return AgentOptionsResponse(providers=[
        ProviderOption(provider="gemini", models=configured_models("gemini")),
        ProviderOption(provider="openai", models=configured_models("openai")),
    ])


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
