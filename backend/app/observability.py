"""Content-free JSON telemetry: never format prompts, headers or raw exceptions."""
import json
import logging
import time
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from uuid import UUID, uuid4

from starlette.types import ASGIApp, Message, Receive, Scope, Send

request_id: ContextVar[str | None] = ContextVar("request_id", default=None)
execution_id: ContextVar[str | None] = ContextVar("execution_id", default=None)
logger = logging.getLogger("agentflow.telemetry")


def _uuid(value: object) -> str | None:
    try:
        return str(UUID(str(value)))
    except (ValueError, TypeError, AttributeError):
        return None


class SafeJSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        # Allowlisting is deliberate. Regex redaction cannot reliably remove
        # private content or encoded credentials from arbitrary SDK messages.
        data = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "event": "application_log",
            "request_id": _uuid(getattr(record, "request_id", None) or request_id.get()),
            "execution_id": _uuid(getattr(record, "execution_id", None) or execution_id.get()),
        }
        event = getattr(record, "event", None)
        if event in {"request_completed", "provider_completed", "execution_completed"}:
            data["event"] = event
        outcome = getattr(record, "outcome", None)
        if outcome in {"completed", "failed", "interrupted"}:
            data["outcome"] = outcome
        for key in ("status", "duration_ms", "input_tokens", "output_tokens", "estimated_cost"):
            value = getattr(record, key, None)
            if isinstance(value, (float, int)) and not isinstance(value, bool):
                data[key] = value
        # Templates come only from registered routes, never from raw URL paths.
        route = getattr(record, "route", None)
        if isinstance(route, str) and route.startswith("/api/") and "?" not in route:
            data["route"] = route[:120]
        status = data.get("status", 0)
        if status in {401, 403}:
            data["category"] = "authentication_or_authorization"
        elif status == 429:
            data["category"] = "rate_limit"
        elif status >= 500:
            data["category"] = "service_failure"
        # No record.getMessage(), exc_info, stack_info or arbitrary extra fields.
        return json.dumps(data, ensure_ascii=True, allow_nan=False)


@contextmanager
def execution_context(identifier: str):
    token = execution_id.set(_uuid(identifier))
    started, outcome = time.monotonic(), "interrupted"
    metrics = {}
    try:
        yield metrics
        outcome = "completed"
    except Exception:
        outcome = "failed"
        raise
    finally:
        logger.info("execution_completed", extra={
            "event": "execution_completed", "request_id": request_id.get(),
            "execution_id": execution_id.get(), "outcome": outcome,
            "duration_ms": round((time.monotonic() - started) * 1000, 2), **metrics,
        })
        execution_id.reset(token)


def configure_production_logging() -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(SafeJSONFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(logging.INFO)
    # Uvicorn may otherwise retain its own handler with raw request URLs/errors.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access", "httpx", "httpcore"):
        library_logger = logging.getLogger(name)
        library_logger.handlers = []
        library_logger.propagate = True


class RequestTelemetry:
    """Pure ASGI wrapper so SSE timings include the complete stream lifetime."""
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        token = request_id.set(str(uuid4()))  # Never trust an inbound correlation ID.
        started, status = time.monotonic(), 500

        async def tracked_send(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                headers = [(k, v) for k, v in message.get("headers", [])
                           if k.lower() != b"x-request-id"]
                headers.append((b"x-request-id", request_id.get().encode("ascii")))
                if scope["path"].startswith("/api/"):
                    headers = [(k, v) for k, v in headers if k.lower() != b"cache-control"]
                    headers.append((b"cache-control", b"no-store"))
                message = {**message, "headers": headers}
            await send(message)

        try:
            await self.app(scope, receive, tracked_send)
        finally:
            route = getattr(scope.get("route"), "path", None)
            logger.info("request_completed", extra={"event": "request_completed",
                        "request_id": request_id.get(),
                        "status": status, "route": route,
                        "duration_ms": round((time.monotonic() - started) * 1000, 2)})
            request_id.reset(token)
