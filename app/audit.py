import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock
from typing import Any

from .config import settings

SENSITIVE_KEYS = {"secret", "token", "jwt", "api_key", "x-api-key", "chat_id", "chat_ids", "authorization", "x-queen-secret", "x-queen-signature"}


def _safe_value(key: str, value: Any) -> Any:
    lowered = key.lower()
    if lowered in SENSITIVE_KEYS or any(marker in lowered for marker in ("secret", "token", "jwt", "api_key", "credential")):
        return "[redacted]"
    if isinstance(value, dict):
        return {item_key: _safe_value(item_key, item_value) for item_key, item_value in value.items()}
    if isinstance(value, list):
        return [_safe_value(key, item) for item in value]
    return value


class AuditService:
    def __init__(self, storage_dir: Path = settings.storage_dir):
        self.storage_dir = storage_dir
        self.audit_path = storage_dir / settings.audit_log_file
        self._lock = RLock()

    def record(self, event: str, request_id: str, **fields: Any) -> None:
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": "audit-record-v1",
            "event": event,
            "request_id": request_id,
            "created_at": datetime.now(UTC).isoformat(),
            "monotonic_time": time.monotonic(),
            **{key: _safe_value(key, value) for key, value in fields.items()},
        }
        with self._lock:
            with self.audit_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")
                handle.flush()
                os.fsync(handle.fileno())


audit_service = AuditService()
