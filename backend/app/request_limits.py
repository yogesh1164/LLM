"""Bound API body buffering before JSON parsing or endpoint side effects."""

from collections.abc import Callable

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send


class RequestBodyLimit:
    def __init__(self, app: ASGIApp, limit: Callable[[], int]):
        self.app = app
        self.limit = limit

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not scope["path"].startswith("/api/"):
            await self.app(scope, receive, send)
            return
        limit = self.limit()
        lengths = [value for key, value in scope.get("headers", [])
                   if key.lower() == b"content-length"]
        # Reject ambiguous framing; do not rely on a client-supplied length to
        # bound chunked input or to prevent a body larger than its declaration.
        if len(lengths) > 1 or (lengths and (not lengths[0] or
                any(char < 48 or char > 57 for char in lengths[0]))):
            await JSONResponse({"detail": "Invalid Content-Length"}, 400)(scope, receive, send)
            return
        # Compare decimal strings without parsing an arbitrarily large integer.
        declared = (lengths[0].lstrip(b"0") or b"0") if lengths else b"0"
        maximum = str(limit).encode("ascii")
        if len(declared) > len(maximum) or (len(declared) == len(maximum) and declared > maximum):
            await JSONResponse({"detail": "Request body exceeds configured limit"}, 413)(scope, receive, send)
            return
        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            chunk = message.get("body", b"")
            if len(body) + len(chunk) > limit:
                await JSONResponse({"detail": "Request body exceeds configured limit"}, 413)(scope, receive, send)
                return
            body.extend(chunk)
            if not message.get("more_body", False):
                break
        replayed = False

        async def replay() -> dict:
            nonlocal replayed
            if not replayed:
                replayed = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()

        await self.app(scope, replay, send)
