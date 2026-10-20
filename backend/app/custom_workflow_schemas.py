"""Request and response contracts for ordered custom-agent workflows."""
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class WorkflowDefinitionInput(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=1000)
    enabled: bool = True
    agent_ids: list[UUID] = Field(min_length=1, max_length=5)
    model_config = ConfigDict(extra="forbid")

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Workflow name cannot be blank")
        return value.strip()

    @field_validator("agent_ids")
    @classmethod
    def unique_agents(cls, value: list[UUID]) -> list[UUID]:
        if len(set(value)) != len(value):
            raise ValueError("An agent may only occur once in a workflow")
        return value


class WorkflowDefinitionRead(BaseModel):
    id: UUID
    name: str
    description: str
    enabled: bool
    agent_ids: list[UUID]
    created_at: datetime
    updated_at: datetime


class WorkflowRunInput(BaseModel):
    task: str = Field(min_length=3, max_length=8000)
    model_config = ConfigDict(extra="forbid")

    @field_validator("task")
    @classmethod
    def strip_task(cls, value: str) -> str:
        if len(value.strip()) < 3:
            raise ValueError("Task must have at least 3 characters")
        return value.strip()


class StepRunRead(BaseModel):
    position: int
    agent_name: str
    provider: str
    model: str
    status: str
    output: str | None
    error: str | None
    input_tokens: int | None
    output_tokens: int | None
    elapsed_ms: int | None
    model_config = ConfigDict(from_attributes=True)


class WorkflowRunRead(BaseModel):
    id: UUID
    workflow_id: UUID | None
    workflow_name: str
    task: str
    status: str
    result: str | None
    error: str | None
    created_at: datetime
    completed_at: datetime | None
    steps: list[StepRunRead]
    model_config = ConfigDict(from_attributes=True)
