"""SQLAlchemy persistence for workflow tasks and agent stage executions."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    create_engine,
    select,
    text,
)
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column,
    relationship,
    sessionmaker,
)

from app.config import settings


class Base(DeclarativeBase):
    pass


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    prompt: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    total_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    estimated_cost: Mapped[float | None] = mapped_column(nullable=True)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    stages: Mapped[list["AgentExecution"]] = relationship(back_populates="task", cascade="all, delete-orphan")


class AgentExecution(Base):
    __tablename__ = "agent_executions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), index=True)
    agent: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(20), default="pending")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    output: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    elapsed_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    task: Mapped[Task] = relationship(back_populates="stages")


class CustomAgent(Base):
    """Persisted Agent Studio configuration, intentionally separate from runtime agents."""

    __tablename__ = "custom_agents"
    __table_args__ = (Index("uq_custom_agents_name_ci", text("lower(name)"), unique=True),)

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    description: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    role: Mapped[str] = mapped_column(String(100), nullable=False)
    system_instructions: Mapped[str] = mapped_column(Text, nullable=False)
    provider: Mapped[str] = mapped_column(String(20), nullable=False)
    model: Mapped[str] = mapped_column(String(120), nullable=False)
    temperature: Mapped[float] = mapped_column(nullable=False, default=0.7)
    max_output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=4096)
    enabled: Mapped[bool] = mapped_column(nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False,
                                                  default=lambda: datetime.now(UTC),
                                                  onupdate=lambda: datetime.now(UTC))
    executions: Mapped[list["CustomAgentExecution"]] = relationship(
        back_populates="agent", cascade="all, delete-orphan"
    )


class CustomAgentExecution(Base):
    """A persisted, non-workflow run of a saved Agent Studio configuration."""

    __tablename__ = "custom_agent_executions"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    agent_id: Mapped[UUID] = mapped_column(ForeignKey("custom_agents.id", ondelete="CASCADE"), index=True)
    task: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="running", index=True)
    provider: Mapped[str] = mapped_column(String(20), nullable=False)
    model: Mapped[str] = mapped_column(String(120), nullable=False)
    result: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    elapsed_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False,
                                                   default=lambda: datetime.now(UTC))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    agent: Mapped[CustomAgent] = relationship(back_populates="executions")


class CustomWorkflow(Base):
    """An ordered definition of saved custom-agent steps."""

    __tablename__ = "custom_workflows"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    enabled: Mapped[bool] = mapped_column(nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC))
    steps: Mapped[list["CustomWorkflowStep"]] = relationship(back_populates="workflow", cascade="all, delete-orphan", order_by="CustomWorkflowStep.position")
    runs: Mapped[list["CustomWorkflowRun"]] = relationship(back_populates="workflow", passive_deletes=True)


class CustomWorkflowStep(Base):
    __tablename__ = "custom_workflow_steps"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    workflow_id: Mapped[UUID] = mapped_column(ForeignKey("custom_workflows.id", ondelete="CASCADE"), nullable=False, index=True)
    agent_id: Mapped[UUID] = mapped_column(ForeignKey("custom_agents.id", ondelete="RESTRICT"), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    workflow: Mapped[CustomWorkflow] = relationship(back_populates="steps")


class CustomWorkflowRun(Base):
    __tablename__ = "custom_workflow_runs"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    workflow_id: Mapped[UUID | None] = mapped_column(ForeignKey("custom_workflows.id", ondelete="SET NULL"), nullable=True, index=True)
    workflow_name: Mapped[str] = mapped_column(String(100), nullable=False)
    task: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="running")
    result: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    workflow: Mapped[CustomWorkflow | None] = relationship(back_populates="runs")
    steps: Mapped[list["CustomWorkflowStepRun"]] = relationship(back_populates="run", cascade="all, delete-orphan", order_by="CustomWorkflowStepRun.position")


class CustomWorkflowStepRun(Base):
    __tablename__ = "custom_workflow_step_runs"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    run_id: Mapped[UUID] = mapped_column(ForeignKey("custom_workflow_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    agent_name: Mapped[str] = mapped_column(String(80), nullable=False)
    provider: Mapped[str] = mapped_column(String(20), nullable=False)
    model: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    output: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    elapsed_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    run: Mapped[CustomWorkflowRun] = relationship(back_populates="steps")


class DurableExecution(Base):
    """One-use idempotency reservation; retained even when its result is deleted."""

    __tablename__ = "durable_executions"
    __table_args__ = (
        UniqueConstraint("scope", "key_digest", name="uq_durable_scope_key"),
        CheckConstraint("state IN ('running', 'completed', 'failed', 'interrupted')",
                        name="ck_durable_state"),
        CheckConstraint("(CASE WHEN task_id IS NULL THEN 0 ELSE 1 END + "
                        "CASE WHEN agent_execution_id IS NULL THEN 0 ELSE 1 END + "
                        "CASE WHEN workflow_run_id IS NULL THEN 0 ELSE 1 END) <= 1",
                        name="ck_durable_one_target"),
        Index("ix_durable_expiry", "state", "lease_expires_at"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    scope: Mapped[str] = mapped_column(String(40), nullable=False)
    operation: Mapped[str] = mapped_column(String(40), nullable=False)
    key_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    request_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(String(20), nullable=False)
    lease_token: Mapped[str] = mapped_column(String(36), nullable=False)
    lease_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    heartbeat_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    provider_started: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    task_id: Mapped[str | None] = mapped_column(
        ForeignKey("tasks.id", ondelete="SET NULL"), unique=True)
    agent_execution_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("custom_agent_executions.id", ondelete="SET NULL"), unique=True)
    workflow_run_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("custom_workflow_runs.id", ondelete="SET NULL"), unique=True)


engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(engine, expire_on_commit=False)


def database_ready() -> bool:
    """Return whether the configured database accepts a simple query."""
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return True
    except Exception:  # noqa: BLE001 - readiness reports dependency availability only.
        return False


def _task_elapsed_ms(task: Task) -> int | None:
    if task.created_at is None:
        return None
    started = task.created_at
    if started.tzinfo is None:
        started = started.replace(tzinfo=UTC)
    ended = task.completed_at or datetime.now(UTC)
    if ended.tzinfo is None:
        ended = ended.replace(tzinfo=UTC)
    return max(0, int((ended - started).total_seconds() * 1000))


def create_task(prompt: str) -> str:
    from app.ownership import claim, scoped
    with SessionLocal.begin() as session:
        if settings.task_retention_days:
            cutoff = datetime.now(UTC) - timedelta(days=settings.task_retention_days)
            expired = session.scalars(scoped(select(Task).where(Task.created_at < cutoff), Task)).all()
            for old_task in expired:
                session.delete(old_task)
        task = Task(prompt=prompt, status="running")
        session.add(task)
        session.flush()
        task_id = task.id
        claim(session, Task, task_id)
        from app.durable_execution import attach
        attach(session, "task_id", task_id)
    return task_id


def delete_task_record(task_id: str) -> bool:
    from app.ownership import get_owned
    with SessionLocal.begin() as session:
        task = get_owned(session, Task, task_id)
        if task is None:
            return False
        session.delete(task)
        return True


def update_task(task_id: str, *, status: str, result: dict | None = None, error: str | None = None,
                total_tokens: int | None = None, estimated_cost: float | None = None) -> None:
    with SessionLocal.begin() as session:
        from app.durable_execution import guard
        guard(session)
        task = session.get(Task, task_id)
        if task:
            task.status = status
            if result is not None:
                task.result = result
            if error is not None:
                task.error = error
            if total_tokens is not None:
                task.total_tokens = total_tokens
            if estimated_cost is not None:
                task.estimated_cost = estimated_cost
            if status in {"completed", "failed", "timed_out", "cancelled"}:
                task.completed_at = datetime.now(UTC)


def start_stage(task_id: str, agent: str) -> str:
    with SessionLocal.begin() as session:
        from app.durable_execution import guard
        guard(session)
        stage = AgentExecution(task_id=task_id, agent=agent, status="running", started_at=datetime.now(UTC))
        session.add(stage)
        session.flush()
        stage_id = stage.id
    return stage_id


def finish_stage(stage_id: str, *, output: str, input_tokens: int, output_tokens: int,
                 elapsed_ms: int = 0) -> None:
    with SessionLocal.begin() as session:
        from app.durable_execution import guard
        guard(session)
        stage = session.get(AgentExecution, stage_id)
        if stage:
            stage.status = "completed"
            stage.output = output
            stage.input_tokens = input_tokens
            stage.output_tokens = output_tokens
            stage.elapsed_ms = elapsed_ms
            stage.completed_at = datetime.now(UTC)


def fail_stage(stage_id: str, error: str, *, status: str = "failed", elapsed_ms: int = 0) -> None:
    with SessionLocal.begin() as session:
        from app.durable_execution import guard
        guard(session)
        stage = session.get(AgentExecution, stage_id)
        if stage:
            stage.status = status
            stage.error = error
            stage.elapsed_ms = elapsed_ms
            stage.completed_at = datetime.now(UTC)


def finish_running_stages(task_id: str, *, status: str, error: str) -> list[str]:
    """Close any in-flight stage when the enclosing workflow times out or is cancelled."""
    with SessionLocal.begin() as session:
        from app.durable_execution import guard
        guard(session)
        stages = session.scalars(select(AgentExecution).where(
            AgentExecution.task_id == task_id, AgentExecution.status == "running"
        ))
        agents = []
        for stage in stages:
            agents.append(stage.agent)
            stage.status = status
            stage.error = error
            stage.completed_at = datetime.now(UTC)
            if stage.started_at:
                started = stage.started_at
                if started.tzinfo is None:
                    started = started.replace(tzinfo=UTC)
                stage.elapsed_ms = max(0, int((stage.completed_at - started).total_seconds() * 1000))
        return agents


def dashboard_data() -> dict:
    from app.ownership import scoped
    with SessionLocal() as session:
        tasks = list(session.scalars(scoped(select(Task).order_by(Task.created_at.desc()).limit(50), Task)))
        known_costs = [task.estimated_cost for task in tasks if task.estimated_cost is not None]
        return {
            "agents": 5,
            "provider": settings.ai_provider,
            "model": settings.active_model,
            "web_search_enabled": (
                settings.gemini_search_grounding_enabled
                if settings.ai_provider == "gemini"
                else settings.openai_web_search_enabled
            ),
            "completed": sum(task.status == "completed" for task in tasks),
            "failed": sum(task.status == "failed" for task in tasks),
            "workflows": sum(task.status == "running" for task in tasks),
            "token_usage": sum(task.total_tokens or 0 for task in tasks),
            "estimated_cost": round(sum(known_costs), 8) if known_costs else None,
            "history": [
                {"id": task.id, "status": task.status, "task": task.prompt,
                 "created_at": task.created_at.isoformat(), "error": task.error,
                 "elapsed_ms": _task_elapsed_ms(task),
                 "total_tokens": task.total_tokens, "estimated_cost": task.estimated_cost,
                 "stages": [{"agent": stage.agent, "status": stage.status, "output": stage.output,
                             "error": stage.error, "input_tokens": stage.input_tokens,
                             "output_tokens": stage.output_tokens, "elapsed_ms": stage.elapsed_ms} for stage in task.stages]}
                for task in tasks
            ],
        }


def get_task(task_id: str) -> dict | None:
    from app.ownership import get_owned
    with SessionLocal() as session:
        task = get_owned(session, Task, task_id)
        if not task:
            return None
        return {
            "id": task.id,
            "task": task.prompt,
            "status": task.status,
            "created_at": task.created_at.isoformat(),
            "completed_at": task.completed_at.isoformat() if task.completed_at else None,
            "elapsed_ms": _task_elapsed_ms(task),
            "total_tokens": task.total_tokens,
            "estimated_cost": task.estimated_cost,
            "result": task.result,
            "error": task.error,
            "stages": [{"agent": stage.agent, "status": stage.status, "output": stage.output,
                        "error": stage.error, "input_tokens": stage.input_tokens,
                        "output_tokens": stage.output_tokens, "elapsed_ms": stage.elapsed_ms} for stage in task.stages],
        }
