"""Opt-in request-owned execution journal. Recovery never invokes a provider."""

import asyncio
import hashlib
import inspect
import json
import logging
import re
from contextlib import aclosing, asynccontextmanager, suppress
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import wraps
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy import func, select

from app import database as db
from app.config import settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/executions", tags=["executions"])
RECOVERY_MESSAGE = "Execution interrupted; provider outcome may be unknown. No automatic replay."


class LeaseLost(RuntimeError):
    """The worker may no longer dispatch or mutate execution state."""


@dataclass(frozen=True)
class Lease:
    id: str
    token: str


current_lease: ContextVar[Lease | None] = ContextVar("execution_lease", default=None)


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def _now(session) -> datetime:
    # PostgreSQL transaction timestamps are fixed at BEGIN; use the actual DB clock.
    if session.bind.dialect.name == "postgresql":
        return session.scalar(select(func.clock_timestamp()))
    return datetime.now(UTC)  # SQLite is for isolated fixtures, not distributed workers.


def guard(session):
    """Lock journal first and hold the lock until the target write commits."""
    lease = current_lease.get()
    if lease is None:
        return None
    row = session.scalar(select(db.DurableExecution).where(
        db.DurableExecution.id == lease.id).with_for_update())
    if (row is None or row.state != "running" or row.lease_token != lease.token
            or _utc(row.lease_expires_at) <= _now(session)):
        raise LeaseLost("Execution lease is no longer valid")
    return row


def attach(session, field: str, identifier) -> None:
    row = guard(session)
    if row is not None:
        if row.task_id or row.agent_execution_id or row.workflow_run_id:
            raise LeaseLost("Execution already has a result record")
        setattr(row, field, identifier)


def before_provider() -> None:
    """Persist dispatch intent BEFORE entering an adapter; uncertainty is sticky."""
    if current_lease.get() is None:
        return
    with db.SessionLocal.begin() as session:
        row = guard(session)
        if not (row.task_id or row.agent_execution_id or row.workflow_run_id):
            raise LeaseLost("Execution result record is missing")
        row.provider_started = True


def _target(session, row):
    for field, model in (("task_id", db.Task), ("agent_execution_id", db.CustomAgentExecution),
                         ("workflow_run_id", db.CustomWorkflowRun)):
        identifier = getattr(row, field)
        if identifier is not None:
            return session.get(model, identifier)
    return None


def _close_target(session, row, now):
    target = _target(session, row)
    if target is None:
        return None
    if target.status == "completed":
        return target
    if isinstance(target, db.Task):
        # Rebuild aggregates if the process died between stage and parent commits.
        result = dict(target.result or {})
        for stage in target.stages:
            if stage.status == "completed":
                key = "plan" if stage.agent == "Orchestrator" else stage.agent.lower()
                result[key] = stage.output
            elif stage.status in {"running", "pending"}:
                stage.status, stage.error, stage.completed_at = "interrupted", RECOVERY_MESSAGE, now
        if any(s.input_tokens is not None or s.output_tokens is not None for s in target.stages):
            result["input_tokens"] = sum(s.input_tokens or 0 for s in target.stages)
            result["output_tokens"] = sum(s.output_tokens or 0 for s in target.stages)
            target.total_tokens = result["total_tokens"] = (
                result["input_tokens"] + result["output_tokens"])
        if result:
            target.result = result
    elif isinstance(target, db.CustomWorkflowRun):
        completed = [s for s in target.steps if s.status == "completed"]
        if completed:
            target.result = max(completed, key=lambda s: s.position).output
        for step in target.steps:
            if step.status in {"running", "pending"}:
                step.status, step.error = "interrupted", RECOVERY_MESSAGE
    if target.status in {"running", "pending"}:
        target.status, target.error, target.completed_at = "interrupted", RECOVERY_MESSAGE, now
    return target


def recover_expired(limit: int = 100) -> int:
    """Only journaled work; never bulk-edit unleased legacy records."""
    with db.SessionLocal.begin() as session:
        now = _now(session)
        rows = session.scalars(select(db.DurableExecution).where(
            db.DurableExecution.state == "running",
            db.DurableExecution.lease_expires_at <= now,
        ).order_by(db.DurableExecution.lease_expires_at).limit(limit)
            .with_for_update(skip_locked=True)).all()
        for row in rows:
            target = _close_target(session, row, now)
            row.state = "completed" if target is not None and target.status == "completed" else "interrupted"
            row.completed_at = now
        return len(rows)


def _view(row) -> dict:
    target_url = None
    if row.task_id:
        target_url = f"/api/tasks/{row.task_id}"
    elif row.workflow_run_id:
        target_url = f"/api/custom-workflows/runs/{row.workflow_run_id}"
    return {"execution_id": row.id, "state": row.state, "operation": row.operation,
            "task_id": row.task_id, "agent_execution_id": str(row.agent_execution_id)
            if row.agent_execution_id else None,
            "workflow_run_id": str(row.workflow_run_id) if row.workflow_run_id else None,
            "result_url": target_url, "provider_attempted": row.provider_started,
            "retry_safety": ("not_started" if not row.provider_started else "do_not_replay"),
            "safe_to_resubmit": row.state in {"failed", "interrupted"} and not row.provider_started,
            "automatic_replay": False}


def reserve(key: str | None, operation: str, payload: dict) -> tuple[Lease | None, dict]:
    if not key or not re.fullmatch(r"[A-Za-z0-9_-]{16,128}", key):
        raise HTTPException(428, "A 16-128 character Idempotency-Key is required")
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    from sqlalchemy.dialects.sqlite import insert as sqlite_insert

    digest = hashlib.sha256(json.dumps({"operation": operation, **payload},
        sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()).hexdigest()
    with db.SessionLocal.begin() as session:
        now = _now(session)
        lease = Lease(str(uuid4()), str(uuid4()))
        values = {"id": lease.id, "scope": "legacy_workspace", "operation": operation,
                  "key_digest": hashlib.sha256(key.encode()).hexdigest(), "request_digest": digest,
                  "state": "running", "lease_token": lease.token, "created_at": now,
                  "heartbeat_at": now,
                  "lease_expires_at": now + timedelta(seconds=settings.execution_lease_seconds),
                  "provider_started": False}
        insert = pg_insert if session.bind.dialect.name == "postgresql" else sqlite_insert
        inserted = session.scalar(insert(db.DurableExecution).values(**values)
            .on_conflict_do_nothing(index_elements=["scope", "key_digest"])
            .returning(db.DurableExecution.id))
        row = session.scalar(select(db.DurableExecution).where(
            db.DurableExecution.scope == "legacy_workspace",
            db.DurableExecution.key_digest == values["key_digest"]))
        if row.request_digest != digest:
            raise HTTPException(409, "Idempotency key was already used for a different request")
        return (lease if inserted else None), _view(row)


def renew() -> None:
    with db.SessionLocal.begin() as session:
        row = guard(session)
        now = _now(session)
        row.heartbeat_at = now
        row.lease_expires_at = now + timedelta(seconds=settings.execution_lease_seconds)


def finish(failed: bool = False) -> None:
    with db.SessionLocal.begin() as session:
        row = guard(session)
        now = _now(session)
        target = _close_target(session, row, now)
        if target is not None and target.status == "completed":
            row.state = "completed"
        else:
            row.state = ("failed" if (target is not None and target.status in {"failed", "timed_out"})
                         or failed else "interrupted")
        row.completed_at = now


@asynccontextmanager
async def owned(lease: Lease):
    token = current_lease.set(lease)
    parent = asyncio.current_task()
    lost = False

    async def heartbeat():
        nonlocal lost
        try:
            while True:
                await asyncio.sleep(settings.execution_heartbeat_seconds)
                renew()
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - any heartbeat failure must stop dispatch.
            lost = True
            parent.cancel()  # Fail closed on DB outage or lease loss; no future dispatch.

    task = asyncio.create_task(heartbeat())
    try:
        yield
        finish()
    except BaseException:
        with suppress(Exception):
            finish(failed=True)
        if lost:
            raise LeaseLost("Execution lease could not be renewed") from None
        raise
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
        current_lease.reset(token)


def execution(operation: str):
    """Keep existing first-response contracts, including the entire SSE lifetime."""
    def decorate(function):
        signature = inspect.signature(function)

        @wraps(function)
        async def wrapped(*args, **kwargs):
            if not settings.durable_execution_enabled:
                return await function(*args, **kwargs)
            arguments = signature.bind(*args, **kwargs).arguments
            http_request = arguments.get("http_request")
            payload = {key: str(value) for key, value in arguments.items()
                       if key in {"agent_id", "workflow_id"}}
            body = arguments.get("request", arguments.get("body"))
            payload["task"] = body.task
            recover_expired()
            lease, view = reserve(http_request.headers.get("Idempotency-Key")
                                  if http_request else None, operation, payload)
            headers = {"X-Execution-ID": view["execution_id"],
                       "Location": f"/api/executions/{view['execution_id']}"}
            if lease is None:
                # Same key NEVER starts work again, including after deletion/failure.
                return JSONResponse(view, 202, headers=headers)
            try:
                if operation == "fixed_stream":
                    # Create the target under the lease; renew until streaming ends.
                    token = current_lease.set(lease)
                    try:
                        response = await function(*args, **kwargs)
                    except BaseException:
                        finish(failed=True)
                        raise
                    finally:
                        current_lease.reset(token)
                    original = response.body_iterator

                    async def stream():
                        try:
                            async with owned(lease), aclosing(original):
                                async for chunk in original:
                                    yield chunk
                        except LeaseLost:
                            yield 'data: {"type":"error","detail":"Execution ownership lost; inspect execution record"}\n\n'

                    response.body_iterator = stream()
                else:
                    async with owned(lease):
                        response = await function(*args, **kwargs)
                if isinstance(response, StreamingResponse):
                    response.headers.update(headers)
                    return response
                from fastapi.encoders import jsonable_encoder
                return JSONResponse(jsonable_encoder(response), headers=headers)
            except LeaseLost:
                raise HTTPException(503, "Execution ownership lost; inspect the execution record",
                                    headers=headers) from None
            except HTTPException as exc:
                exc.headers = {**(exc.headers or {}), **headers}
                raise
        return wrapped
    return decorate


@router.get("/{execution_id}")
async def execution_status(execution_id: str):
    if not settings.durable_execution_enabled:
        raise HTTPException(503, "Durable execution is disabled")
    with db.SessionLocal() as session:
        row = session.get(db.DurableExecution, execution_id)
        if row is None:
            raise HTTPException(404, "Execution not found")
        return _view(row)


async def _recovery_loop():
    while True:
        await asyncio.sleep(settings.execution_recovery_seconds)
        try:
            recover_expired()
        except Exception:  # noqa: BLE001 - periodic DB failure is retried without provider work.
            logger.error("Execution recovery check failed")


@asynccontextmanager
async def lifespan(app):
    if not settings.durable_execution_enabled:
        yield
        return
    # No create_all or migrations on startup. Missing schema is a startup failure.
    with db.SessionLocal() as session:
        if settings.app_env == "production" and session.bind.dialect.name != "postgresql":
            raise RuntimeError("Production durable execution requires PostgreSQL")
        session.execute(select(db.DurableExecution).limit(0))
    recover_expired()
    task = asyncio.create_task(_recovery_loop())
    try:
        yield
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
