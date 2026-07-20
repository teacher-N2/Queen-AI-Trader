import time
from datetime import UTC, datetime

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse, Response

from .config import settings
from .metrics import metrics
from .observability import log_event
from .runtime_context import RequestContext, new_id, reset_context, set_context


class ProductionMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        request_id = request.headers.get("x-request-id") or new_id("req")
        correlation_id = request.headers.get("x-correlation-id") or new_id("corr")
        token = set_context(RequestContext(request_id=request_id, correlation_id=correlation_id))
        started = time.perf_counter()
        response: Response | None = None
        try:
            body_size = int(request.headers.get("content-length") or 0)
            if body_size > settings.max_request_body_bytes:
                metrics.increment("requests_failed_total")
                response = self._error(413, "request_too_large", "request body too large", request_id, correlation_id)
                return response
            response = await call_next(request)
            return response
        finally:
            duration_ms = round((time.perf_counter() - started) * 1000, 2)
            metrics.increment("requests_total")
            metrics.observe_duration("request_duration", duration_ms)
            try:
                if response is not None:
                    response.headers["x-request-id"] = request_id
                    response.headers["x-correlation-id"] = correlation_id
                    response.headers["x-queen-processing-ms"] = str(duration_ms)
                    response.headers["x-content-type-options"] = "nosniff"
                    response.headers["x-frame-options"] = "DENY"
                    response.headers["referrer-policy"] = "no-referrer"
                log_event(
                    "http_request_completed",
                    request_id=request_id,
                    correlation_id=correlation_id,
                    operation=f"{request.method} {request.url.path}",
                    duration_ms=duration_ms,
                    status=getattr(response, "status_code", None),
                )
            finally:
                reset_context(token)

    def _error(self, status_code: int, code: str, message: str, request_id: str, correlation_id: str) -> JSONResponse:
        return JSONResponse(
            status_code=status_code,
            content={
                "error_code": code,
                "message": message,
                "request_id": request_id,
                "correlation_id": correlation_id,
                "timestamp": datetime.now(UTC).isoformat(),
                "retryable": False,
            },
        )
