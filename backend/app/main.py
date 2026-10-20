import asyncio
import hmac
import json
import logging
import threading
import time
from collections import defaultdict, deque

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse

from app.config import settings
from app.custom_agents import router as custom_agents_router
from app.database import (
    create_task,
    dashboard_data,
    database_ready,
    delete_task_record,
    finish_running_stages,
    get_task,
    update_task,
)
from app.providers import ProviderConfigurationError, validate_provider
from app.schemas import (
    DashboardResponse,
    ExecutionResponse,
    TaskDetail,
    WorkflowRequest,
    WorkflowResponse,
)
from app.workflow import StageTimeoutError, run_workflow

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("agentflow.api")
app = FastAPI(title="AgentFlow AI API", version="0.2.0")
app.include_router(custom_agents_router)
_rate_events: dict[str, deque[float]] = defaultdict(deque)
_rate_limit_lock = threading.Lock()


async def _check_rate_limit(request: Request) -> None:
    now = time.monotonic()
    host = request.client.host if request.client else "unknown"
    with _rate_limit_lock:
        events = _rate_events[host]
        while events and events[0] < now - 60:
            events.popleft()
        if len(events) >= settings.rate_limit_per_minute:
            raise HTTPException(status_code=429, detail="Too many workflow requests; try again shortly")
        events.append(now)
        # Bound storage for clients that have not returned within the active window.
        if len(_rate_events) > 10_000:
            expired = [key for key, values in _rate_events.items() if not values or values[-1] < now - 60]
            for key in expired:
                _rate_events.pop(key, None)
            while len(_rate_events) > 10_000:
                _rate_events.pop(min(_rate_events, key=lambda key: _rate_events[key][-1]), None)


@app.middleware("http")
async def require_api_token(request: Request, call_next):
    if request.url.path.startswith("/api/") and request.url.path not in {
        "/api/health", "/api/ready",
    }:
        configured = settings.api_access_token
        if not configured:
            return JSONResponse({"detail": "API access token is not configured"}, status_code=503)
        provided = request.headers.get("authorization", "")
        expected = configured.get_secret_value()
        if not provided.startswith("Bearer ") or not hmac.compare_digest(provided[7:], expected):
            return JSONResponse({"detail": "Authentication required"}, status_code=401,
                                headers={"WWW-Authenticate": "Bearer"})
    return await call_next(request)


def _require_ai() -> None:
    try:
        validate_provider(settings)
    except ProviderConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None


def _safe_provider_error(exc: Exception) -> tuple[int, str]:
    exceptions = [exc]
    cause = exc.__cause__ or exc.__context__ or getattr(exc, "original_exception", None)
    while cause is not None and cause not in exceptions:
        exceptions.append(cause)
        cause = cause.__cause__ or cause.__context__ or getattr(cause, "original_exception", None)
    status = next((getattr(error, "status_code", None) or getattr(error, "code", None)
                   for error in exceptions
                   if getattr(error, "status_code", None) or getattr(error, "code", None)), None)
    name = " ".join(type(error).__name__.lower() for error in exceptions)
    text = " ".join(str(error).lower() for error in exceptions)
    diagnostic = next((getattr(error, "provider_message", None) for error in exceptions
                       if getattr(error, "provider_message", None)), None)
    diagnostic = str(diagnostic or "").replace(settings.gemini_api_key.get_secret_value(), "[redacted]") \
        if settings.gemini_api_key else str(diagnostic or "")
    diagnostic = " ".join(diagnostic.split())[:500]
    if status == 503:
        return 503, f"Gemini is temporarily unavailable (HTTP 503).{(' ' + diagnostic) if diagnostic else ' Try again shortly.'}"
    if status == 429 and any(term in text for term in (
        "quota", "billing", "daily limit", "per day", "resource_exhausted",
    )):
        return 429, "AI provider quota or rate limit reached. Try again later."
    if status == 429 or "ratelimit" in name:
        return 429, "AI provider is temporarily rate limited. Retry after a short pause."
    if "grounding" in text and any(
        phrase in text for phrase in ("not available", "not supported", "not enabled", "billing")
    ):
        return (
            403,
            (
                "Gemini Search grounding is unavailable for this API tier or billing setup. "
                "Disable grounding or check Google AI Studio billing and quotas."
            ),
        )
    if (status in {401, 403} or "authentication" in name or "permissiondenied" in name
            or ("api key" in text and any(token in text for token in ("invalid", "not valid", "unauthorized")))):
        return 502, "AI provider rejected its configured API key. Check the key and provider access."
    if (status == 404 or "modelnotfound" in name
            or any(phrase in text for phrase in ("unsupported model", "model not found", "unknown model"))):
        return 502, "The selected AI model is unavailable or unsupported."
    if "tool" in text and any(token in text for token in ("unsupported", "not supported", "unknown")):
        return 502, "The selected AI provider does not support a required research tool."
    if "input exceeded the configured" in text:
        return 502, "Generated workflow context exceeded the configured stage input limit."
    if any(token in name for token in ("connect", "timeout", "network")):
        return 502, "Could not reach the AI provider. Check the network and try again."
    if diagnostic:
        return 502, f"AI provider request failed: {diagnostic}"
    return 502, "AI provider request failed. Check provider settings and try again."


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "agentflow-api"}


@app.get("/api/ready")
async def readiness() -> dict[str, str]:
    if not database_ready():
        raise HTTPException(status_code=503, detail="Database is unavailable")
    return {"status": "ready", "service": "agentflow-api"}


async def _execute(task: str) -> dict:
    task_id = create_task(task)
    try:
        result = await asyncio.wait_for(run_workflow(task, task_id), timeout=settings.workflow_timeout_seconds)
        stored = {k: v for k, v in result.items() if k != "sources"}
        stored["sources"] = [source.model_dump(mode="json") for source in result["sources"]]
        update_task(task_id, status="completed", result=stored,
                    total_tokens=result["total_tokens"], estimated_cost=result["estimated_cost"])
        result["id"] = task_id
        return result
    except TimeoutError as exc:
        is_stage_timeout = isinstance(exc, StageTimeoutError)
        message = str(exc) if is_stage_timeout else (
            f"Workflow exceeded its {settings.workflow_timeout_seconds}s total timeout"
        )
        if not is_stage_timeout:
            finish_running_stages(task_id, status="timed_out", error=message)
        update_task(task_id, status="failed", error=message)
        raise HTTPException(status_code=504, detail=message) from exc
    except asyncio.CancelledError:
        finish_running_stages(task_id, status="cancelled", error="Workflow cancelled")
        update_task(task_id, status="failed", error="Workflow cancelled")
        raise
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001 - provider SDK errors need safe public messages.
        status, message = _safe_provider_error(exc)
        logger.warning("Workflow request failed (%s)", type(exc).__name__)
        update_task(task_id, status="failed", error=message)
        raise HTTPException(status_code=status, detail=message) from None


@app.post("/api/workflows/collaborate", response_model=WorkflowResponse)
async def collaborate(request: WorkflowRequest, http_request: Request) -> WorkflowResponse:
    await _check_rate_limit(http_request)
    _require_ai()
    result = await _execute(request.task)
    return WorkflowResponse(research=result["research"], analysis=result["analysis"])


@app.post("/api/workflows/execute", response_model=ExecutionResponse)
async def execute_workflow(request: WorkflowRequest, http_request: Request) -> ExecutionResponse:
    await _check_rate_limit(http_request)
    _require_ai()
    result = await _execute(request.task)
    task_id = result.pop("id")
    return ExecutionResponse(task_id=task_id, status="completed", **result)


@app.post("/api/workflows/stream")
async def stream_workflow(request: WorkflowRequest, http_request: Request) -> StreamingResponse:
    await _check_rate_limit(http_request)
    _require_ai()
    task_id = create_task(request.task)

    async def events():
        async def send(event: dict) -> None:
            yield_value = f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
            queue.put_nowait(yield_value)

        queue: asyncio.Queue[str | None] = asyncio.Queue()

        async def execute_task() -> None:
            try:
                result = await asyncio.wait_for(
                    run_workflow(request.task, task_id, lambda event: send(event)),
                    timeout=settings.workflow_timeout_seconds,
                )
                stored = {k: v for k, v in result.items() if k != "sources"}
                stored["sources"] = [source.model_dump(mode="json") for source in result["sources"]]
                update_task(task_id, status="completed", result=stored,
                            total_tokens=result["total_tokens"], estimated_cost=result["estimated_cost"])
                await send({"type": "result", "task_id": task_id, **result})
            except TimeoutError as exc:
                is_stage_timeout = isinstance(exc, StageTimeoutError)
                message = str(exc) if is_stage_timeout else (
                    f"Workflow exceeded its {settings.workflow_timeout_seconds}s total timeout"
                )
                if not is_stage_timeout:
                    active_agents = finish_running_stages(task_id, status="timed_out", error=message)
                    for agent in active_agents:
                        await send({"type": "stage", "agent": agent, "status": "timed_out",
                                    "error": message})
                update_task(task_id, status="failed", error=message)
                await send({"type": "error", "detail": message, "status": "timed_out"})
            except asyncio.CancelledError:
                active_agents = finish_running_stages(task_id, status="cancelled", error="Workflow cancelled")
                for agent in active_agents:
                    await send({"type": "stage", "agent": agent, "status": "cancelled",
                                "error": "Workflow cancelled"})
                update_task(task_id, status="failed", error="Workflow cancelled")
                await send({"type": "error", "detail": "Workflow cancelled", "status": "cancelled"})
                raise
            except StageTimeoutError as exc:
                message = str(exc)
                update_task(task_id, status="failed", error=message)
                await send({"type": "error", "detail": message, "status": "timed_out"})
            except Exception as exc:  # noqa: BLE001 - provider SDK errors need safe stream messages.
                _, message = _safe_provider_error(exc)
                logger.warning("Stream workflow failed (%s)", type(exc).__name__)
                update_task(task_id, status="failed", error=message)
                await send({"type": "error", "detail": message})
            finally:
                queue.put_nowait(None)

        task = asyncio.create_task(execute_task())
        try:
            yield f"data: {json.dumps({'type': 'started', 'task_id': task_id})}\n\n"
            while True:
                try:
                    item = await asyncio.wait_for(queue.get(), timeout=15)
                except TimeoutError:
                    yield ": keep-alive\n\n"
                    continue
                if item is None:
                    break
                yield item
            await task
        finally:
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

    return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/dashboard", response_model=DashboardResponse)
async def dashboard() -> DashboardResponse:
    return DashboardResponse(**dashboard_data())


@app.get("/api/tasks/{task_id}", response_model=TaskDetail)
async def task_detail(task_id: str) -> TaskDetail:
    task = get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return TaskDetail(**task)


@app.delete("/api/tasks/{task_id}", status_code=204)
async def remove_task(task_id: str) -> Response:
    if not delete_task_record(task_id):
        raise HTTPException(status_code=404, detail="Task not found")
    return Response(status_code=204)


# Wrap the complete ASGI app so CORS headers are also present on unhandled 500 responses.
# This keeps browser diagnostics useful while still returning the real server error.
app = CORSMiddleware(
    app=app,
    allow_origins=settings.allowed_frontend_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["Content-Type", "Authorization"],
)
