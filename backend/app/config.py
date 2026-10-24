from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, computed_field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: Literal["development", "production"] = "development"
    ai_provider: Literal["gemini", "openai"] = "gemini"
    api_access_token: SecretStr | None = None
    gemini_api_key: SecretStr | None = None
    gemini_model: str = "gemini-3.8-flash"
    # Search grounding may incur usage charges; require an explicit opt-in.
    gemini_search_grounding_enabled: bool = False
    openai_api_key: SecretStr | None = None
    openai_model: str = "gpt-5-mini"
    frontend_origins: str = "http://localhost:3000,http://127.0.0.1:3000"
    # Backwards compatibility for existing deployments using FRONTEND_ORIGIN.
    frontend_origin: str | None = None
    # Leave enough time for five sequential provider calls, including a slower final review.
    workflow_timeout_seconds: int = Field(default=600, ge=10, le=1800)
    agent_timeout_seconds: int = Field(default=90, ge=5, le=300)
    provider_retry_attempts: int = Field(default=2, ge=0, le=5)
    provider_max_concurrency: int = Field(default=4, ge=1, le=16)
    provider_retry_base_delay_seconds: float = Field(default=0.5, ge=0.05, le=10)
    provider_retry_max_delay_seconds: float = Field(default=4, ge=0.1, le=30)
    orchestrator_timeout_seconds: int | None = Field(default=None, ge=5, le=600)
    research_timeout_seconds: int | None = Field(default=None, ge=5, le=600)
    analysis_timeout_seconds: int | None = Field(default=None, ge=5, le=600)
    report_timeout_seconds: int | None = Field(default=None, ge=5, le=600)
    review_timeout_seconds: int = Field(default=180, ge=5, le=600)
    custom_agent_timeout_seconds: int = Field(default=90, ge=5, le=300)
    custom_agent_max_input_tokens: int = Field(default=8_000, ge=256, le=100_000)
    max_stage_output_chars: int = Field(default=12_000, ge=500, le=100_000)
    max_stage_input_chars: int = Field(default=40_000, ge=1_000, le=200_000)
    max_model_calls_per_workflow: int = Field(default=5, ge=5, le=20)
    database_url: str = Field(
        default="postgresql+psycopg://agentflow:agentflow@localhost:5432/agentflow", repr=False,
    )
    task_retention_days: int = Field(default=0, ge=0, le=3650)
    rate_limit_per_minute: int = Field(default=10, ge=1, le=600)
    max_request_body_bytes: int = Field(default=262_144, ge=1024, le=1_048_576)
    # Explicit opt-in only after the additive migration is approved/applied.
    durable_execution_enabled: bool = False
    execution_lease_seconds: int = Field(default=60, ge=10, le=600)
    execution_heartbeat_seconds: float = Field(default=5, ge=1, le=60)
    execution_recovery_seconds: float = Field(default=15, ge=1, le=60)
    input_token_cost_per_million: float = Field(default=0.25, ge=0)
    cached_input_token_cost_per_million: float = Field(default=0.025, ge=0)
    output_token_cost_per_million: float = Field(default=2.0, ge=0)
    openai_web_search_enabled: bool = True

    @field_validator("api_access_token", mode="before")
    @classmethod
    def empty_access_token_is_unset(cls, value):
        return None if value == "" else value

    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[2] / ".env",
        extra="ignore",
        hide_input_in_errors=True,
    )

    @computed_field
    @property
    def active_model(self) -> str:
        return self.gemini_model if self.ai_provider == "gemini" else self.openai_model

    @computed_field
    @property
    def allowed_frontend_origins(self) -> list[str]:
        origins = [origin.strip() for origin in self.frontend_origins.split(",") if origin.strip()]
        if self.frontend_origin and self.frontend_origin.strip() not in origins:
            origins.append(self.frontend_origin.strip())
        return origins

    @model_validator(mode="after")
    def validate_model_name(self) -> "Settings":
        if self.execution_heartbeat_seconds * 3 >= self.execution_lease_seconds:
            raise ValueError("Execution heartbeat must be less than one third of the lease")
        model = self.active_model.strip()
        if not model or any(char.isspace() for char in model):
            raise ValueError("The configured AI model name is invalid")
        if self.api_access_token and len(self.api_access_token.get_secret_value()) < 32:
            raise ValueError("API_ACCESS_TOKEN must contain at least 32 characters")
        for origin in self.allowed_frontend_origins:
            try:
                parsed = urlsplit(origin)
                valid = (parsed.scheme in {"http", "https"} and parsed.hostname
                         and not parsed.username and not parsed.password
                         and not parsed.path and not parsed.query and not parsed.fragment
                         and "*" not in origin and not any(c.isspace() for c in origin))
                _ = parsed.port
            except ValueError:
                valid = False
            if not valid:
                raise ValueError("CORS origins must be explicit HTTP(S) origins without paths")
            if self.app_env == "production" and parsed.scheme != "https":
                raise ValueError("Production CORS origins must use HTTPS")
        if self.app_env == "production":
            if not self.api_access_token:
                raise ValueError("Production requires API_ACCESS_TOKEN")
            if not self.allowed_frontend_origins:
                raise ValueError("Production requires explicit FRONTEND_ORIGINS")
            key = self.gemini_api_key if self.ai_provider == "gemini" else self.openai_api_key
            if not key or not key.get_secret_value().strip():
                raise ValueError("Production requires the selected provider API key")
        return self


settings = Settings()

