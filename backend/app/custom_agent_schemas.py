"""API schemas for saved custom agents (not workflow runtime agents)."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.config import settings

AgentProvider = Literal["gemini", "openai"]


def configured_models(provider: AgentProvider) -> list[str]:
    """Only offer models currently configured and supported by this backend."""
    model = settings.gemini_model if provider == "gemini" else settings.openai_model
    return [model]


class AgentConfigCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    description: str = Field(default="", max_length=500)
    role: str = Field(min_length=1, max_length=100)
    system_instructions: str = Field(min_length=1, max_length=8_000)
    provider: AgentProvider
    model: str = Field(min_length=1, max_length=120)
    temperature: float = Field(default=0.7, ge=0, le=2)
    max_output_tokens: int = Field(default=4096, ge=1, le=32_768)
    enabled: bool = True

    model_config = ConfigDict(extra="forbid")

    @field_validator("name", "role", "system_instructions")
    @classmethod
    def strip_required_strings(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("This field cannot be blank")
        return value

    @field_validator("description")
    @classmethod
    def strip_description(cls, value: str) -> str:
        return value.strip()

    @model_validator(mode="after")
    def validate_model_for_provider(self) -> "AgentConfigCreate":
        if self.model not in configured_models(self.provider):
            raise ValueError(
                f"Unsupported model for {self.provider}; choose one of: "
                f"{', '.join(configured_models(self.provider))}"
            )
        return self


class AgentConfigPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    description: str | None = Field(default=None, max_length=500)
    role: str | None = Field(default=None, min_length=1, max_length=100)
    system_instructions: str | None = Field(default=None, min_length=1, max_length=8_000)
    provider: AgentProvider | None = None
    model: str | None = Field(default=None, min_length=1, max_length=120)
    temperature: float | None = Field(default=None, ge=0, le=2)
    max_output_tokens: int | None = Field(default=None, ge=1, le=32_768)
    enabled: bool | None = None

    model_config = ConfigDict(extra="forbid")


class AgentConfigRead(AgentConfigCreate):
    id: UUID
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ProviderOption(BaseModel):
    provider: AgentProvider
    models: list[str]


class AgentOptionsResponse(BaseModel):
    providers: list[ProviderOption]
