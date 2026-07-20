import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any

from .config import settings
from .runtime_context import get_context

SENSITIVE_MARKERS = ("secret", "token", "jwt", "api_key", "authorization", "credential", "password", "signature")


def redact(value: Any, key: str = "") -> Any:
    if key and any(marker in key.lower() for marker in SENSITIVE_MARKERS):
        return "[redacted]"
    if isinstance(value, dict):
        return {item_key: redact(item_value, item_key) for item_key, item_value in value.items()}
    if isinstance(value, list):
        return [redact(item) for item in value]
    return value


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        context = get_context()
        payload = {
            "timestamp": datetime.now(UTC).isoformat(),
            "log_level": record.levelname,
            "service": settings.app_name,
            "environment": settings.environment,
            "event_name": getattr(record, "event_name", record.getMessage()),
            "request_id": getattr(record, "request_id", context.request_id),
            "correlation_id": getattr(record, "correlation_id", context.correlation_id),
            "signal_id": getattr(record, "signal_id", context.signal_id),
            "trade_id": getattr(record, "trade_id", context.trade_id),
            "delivery_id": getattr(record, "delivery_id", context.delivery_id),
            "route": getattr(record, "route", None),
            "operation": getattr(record, "operation", None),
            "duration_ms": getattr(record, "duration_ms", None),
            "retry_count": getattr(record, "retry_count", None),
            "status": getattr(record, "status", None),
            "error_type": getattr(record, "error_type", None),
            "error_message": getattr(record, "error_message", None),
        }
        if record.exc_info and settings.environment != "production":
            payload["stack_trace"] = self.formatException(record.exc_info)
        return json.dumps(redact({key: value for key, value in payload.items() if value is not None}), separators=(",", ":"))


def configure_logging() -> None:
    root = logging.getLogger()
    root.handlers.clear()
    handler = logging.StreamHandler(sys.stdout)
    if settings.log_format.lower() == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    root.addHandler(handler)
    root.setLevel(settings.log_level.upper())


logger = logging.getLogger("queen_ai_trader")


def log_event(event_name: str, level: int = logging.INFO, **fields: Any) -> None:
    safe_fields = redact(fields)
    logger.log(level, event_name, extra={"event_name": event_name, **safe_fields})
