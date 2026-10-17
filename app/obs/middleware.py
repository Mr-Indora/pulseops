"""Pure ASGI middleware: request id, RED metrics by route template, one JSON log line per request."""
import time
import uuid

import structlog

from app.obs.metrics import IN_PROGRESS, REQUEST_SECONDS, REQUESTS

log = structlog.get_logger("pulseops.request")


class ObsMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["path"] == "/metrics":  # /metrics must not measure itself
            return await self.app(scope, receive, send)

        request_id = str(uuid.uuid4())
        scope.setdefault("state", {})["request_id"] = request_id  # what request.state.request_id reads
        structlog.contextvars.bind_contextvars(request_id=request_id)
        status, error_type = 500, None
        start = time.perf_counter()
        IN_PROGRESS.inc()

        async def send_with_id(message):
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                message["headers"] = [*message.get("headers", []), (b"x-request-id", request_id.encode())]
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        except Exception as exc:
            status, error_type = 500, type(exc).__name__
            raise
        finally:
            IN_PROGRESS.dec()
            duration = time.perf_counter() - start
            # The router stores the matched route in scope; read it after the call. No match
            # (404) collapses to one label so random paths cannot explode cardinality.
            route = getattr(scope.get("route"), "path", "unmatched")
            method = scope["method"]
            REQUESTS.labels(method, route, str(status)).inc()
            REQUEST_SECONDS.labels(method, route).observe(duration)
            fields = {"method": method, "route": route, "status": status,
                      "duration_ms": round(duration * 1000, 2)}
            if error_type:
                log.error("request", error_type=error_type, **fields)
            else:
                log.info("request", **fields)
            structlog.contextvars.unbind_contextvars("request_id")
