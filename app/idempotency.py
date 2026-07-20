import hashlib
import json
import os
import time
from enum import Enum
from pathlib import Path
from threading import RLock
from typing import Any

from .config import settings
from .observability import redact
from .production_errors import IdempotencyConflictError, PersistenceError

SCHEMA_VERSION = "operation-state-v1"


class DeliveryOperationState(str, Enum):
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    RETRY_SCHEDULED = "RETRY_SCHEDULED"
    DELIVERED = "DELIVERED"
    FAILED = "FAILED"
    DEAD_LETTERED = "DEAD_LETTERED"
    CANCELLED = "CANCELLED"


class WebhookOperationState(str, Enum):
    RECEIVED = "RECEIVED"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED_RETRYABLE = "FAILED_RETRYABLE"
    FAILED_PERMANENT = "FAILED_PERMANENT"


class OperationStore:
    def __init__(self, storage_dir: Path = settings.storage_dir):
        self.storage_dir = storage_dir
        self.path = storage_dir / settings.idempotency_records_file
        self.quarantine_path = storage_dir / f"{settings.idempotency_records_file}.quarantine"
        self._lock = RLock()

    def fingerprint(self, payload: dict[str, Any]) -> str:
        encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def begin_delivery(self, key: str, payload: dict[str, Any]) -> tuple[str, dict[str, Any] | None]:
        return self._begin(
            scope="delivery",
            key=key,
            payload=payload,
            active_state=DeliveryOperationState.IN_PROGRESS.value,
            success_state=DeliveryOperationState.DELIVERED.value,
            retryable_states={
                DeliveryOperationState.PENDING.value,
                DeliveryOperationState.RETRY_SCHEDULED.value,
                DeliveryOperationState.FAILED.value,
            },
            stale_states={DeliveryOperationState.IN_PROGRESS.value},
            permanent_states={DeliveryOperationState.DEAD_LETTERED.value, DeliveryOperationState.CANCELLED.value},
            lease_seconds=settings.delivery_operation_lease_seconds,
        )

    def mark_delivery(
        self,
        key: str,
        state: DeliveryOperationState,
        *,
        result: dict[str, Any] | None = None,
        error: str | None = None,
        next_retry_at: float | None = None,
    ) -> None:
        self._transition("delivery", key, state.value, result=result, error=error, next_retry_at=next_retry_at)

    def begin_webhook(self, key: str, payload: dict[str, Any]) -> tuple[str, dict[str, Any] | None]:
        return self._begin(
            scope="webhook",
            key=key,
            payload=payload,
            active_state=WebhookOperationState.PROCESSING.value,
            success_state=WebhookOperationState.COMPLETED.value,
            retryable_states={WebhookOperationState.RECEIVED.value, WebhookOperationState.FAILED_RETRYABLE.value},
            stale_states={WebhookOperationState.PROCESSING.value},
            permanent_states={WebhookOperationState.FAILED_PERMANENT.value},
            lease_seconds=settings.webhook_operation_lease_seconds,
        )

    def mark_webhook(self, key: str, state: WebhookOperationState, *, result: dict[str, Any] | None = None, error: str | None = None) -> None:
        self._transition("webhook", key, state.value, result=result, error=error)

    def recoverable_operations(self, *, include_private: bool = False) -> list[dict[str, Any]]:
        now = time.time()
        with self._lock:
            records = self._read_records_locked()
            recoverable = []
            for record in records:
                state = record.get("state")
                lease_expires_at = float(record.get("lease_expires_at") or 0)
                if state in {
                    DeliveryOperationState.PENDING.value,
                    DeliveryOperationState.RETRY_SCHEDULED.value,
                    WebhookOperationState.RECEIVED.value,
                    WebhookOperationState.FAILED_RETRYABLE.value,
                }:
                    recoverable.append(self._public_record(record, include_private))
                elif state in {DeliveryOperationState.IN_PROGRESS.value, WebhookOperationState.PROCESSING.value} and lease_expires_at <= now:
                    recoverable.append(self._public_record(record, include_private))
            return recoverable

    def all_operations(self, *, include_private: bool = False) -> list[dict[str, Any]]:
        with self._lock:
            return [self._public_record(record, include_private) for record in self._read_records_locked()]

    def check_or_record(self, scope: str, key: str, payload: dict[str, Any], result: dict[str, Any] | None = None) -> dict[str, Any] | None:
        action, stored = self._begin(
            scope=scope,
            key=key,
            payload=payload,
            active_state="recorded",
            success_state="recorded",
            retryable_states=set(),
            stale_states=set(),
            permanent_states=set(),
            lease_seconds=settings.webhook_operation_lease_seconds,
        )
        if action == "started":
            self._transition(scope, key, "recorded", result=result)
            return None
        return stored

    def _begin(
        self,
        *,
        scope: str,
        key: str,
        payload: dict[str, Any],
        active_state: str,
        success_state: str,
        retryable_states: set[str],
        stale_states: set[str],
        permanent_states: set[str],
        lease_seconds: int,
    ) -> tuple[str, dict[str, Any] | None]:
        now = time.time()
        fingerprint = self.fingerprint(payload)
        with self._lock:
            records = self._read_records_locked()
            record = self._find(records, scope, key)
            if record:
                if record.get("fingerprint") != fingerprint:
                    raise IdempotencyConflictError("idempotency key reused with conflicting payload")
                state = record.get("state")
                lease_expires_at = float(record.get("lease_expires_at") or 0)
                if state == success_state:
                    return "completed", record.get("result")
                if state in permanent_states:
                    return "permanent", record.get("result")
                if state in retryable_states or (state in stale_states and lease_expires_at <= now):
                    record.update(
                        {
                            "state": active_state,
                            "updated_at": now,
                            "lease_expires_at": now + lease_seconds,
                    "attempt_count": int(record.get("attempt_count") or 0) + 1,
                    "last_resume_at": now,
                        }
                    )
                    self._write_records_locked(records)
                    return "started", None
                return "active", record.get("result")
            records.append(
                {
                    "schema_version": SCHEMA_VERSION,
                    "scope": scope,
                    "key": key,
                    "fingerprint": fingerprint,
                    "state": active_state,
                    "created_at": now,
                    "updated_at": now,
                    "lease_expires_at": now + lease_seconds,
                    "expires_at": now + settings.idempotency_retention_seconds,
                    "attempt_count": 1,
                    "result": None,
                    "last_error": None,
                    "payload": payload,
                    "next_retry_at": None,
                }
            )
            self._write_records_locked(records)
            return "started", None

    def _transition(
        self,
        scope: str,
        key: str,
        state: str,
        *,
        result: dict[str, Any] | None = None,
        error: str | None = None,
        next_retry_at: float | None = None,
    ) -> None:
        now = time.time()
        with self._lock:
            records = self._read_records_locked()
            record = self._find(records, scope, key)
            if not record:
                raise PersistenceError("operation record not found")
            record.update(
                {
                    "state": state,
                    "updated_at": now,
                    "lease_expires_at": None,
                    "result": result if result is not None else record.get("result"),
                    "last_error": error,
                    "next_retry_at": next_retry_at,
                }
            )
            self._write_records_locked(records)

    def _find(self, records: list[dict[str, Any]], scope: str, key: str) -> dict[str, Any] | None:
        for record in records:
            if record.get("scope") == scope and record.get("key") == key:
                return record
        return None

    def _public_record(self, record: dict[str, Any], include_private: bool) -> dict[str, Any]:
        if include_private:
            return dict(record)
        public = dict(record)
        if public.get("scope") == "delivery":
            public["key"] = self.fingerprint({"key": public.get("key")})
        if "payload" in public:
            public["payload"] = self._redact_private_payload(public["payload"])
        if "result" in public:
            public["result"] = redact(public["result"])
        return public

    def _redact_private_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        safe = redact(payload)
        for key in list(safe.keys()):
            if "private" in key.lower() or key.lower() in {"destination", "message_body"}:
                safe[key] = "[redacted]"
        if "delivery_operation_id" in safe:
            safe["delivery_operation_id"] = self.fingerprint({"delivery_operation_id": safe["delivery_operation_id"]})
        return safe

    def _read_records_locked(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        records: list[dict[str, Any]] = []
        corrupt: list[dict[str, Any]] = []
        for line_number, line in enumerate(self.path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
                if record.get("schema_version") != SCHEMA_VERSION:
                    raise ValueError("unsupported schema version")
                records.append(record)
            except (json.JSONDecodeError, ValueError) as exc:
                corrupt.append(
                    {
                        "source_filename": str(self.path),
                        "line_number": line_number,
                        "timestamp": time.time(),
                        "error_type": exc.__class__.__name__,
                        "raw_line": line,
                    }
                )
        if corrupt:
            self._append_quarantine_locked(corrupt)
            if settings.environment == "production":
                raise PersistenceError("corrupt operation records quarantined")
        return records

    def _write_records_locked(self, records: list[dict[str, Any]]) -> None:
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            backup_path = self.path.with_suffix(self.path.suffix + ".bak")
            backup_path.write_bytes(self.path.read_bytes())
        tmp_path = self.path.with_suffix(self.path.suffix + ".tmp")
        with tmp_path.open("w", encoding="utf-8") as handle:
            for record in records:
                handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, self.path)
        self._fsync_dir()

    def _append_quarantine_locked(self, records: list[dict[str, Any]]) -> None:
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        with self.quarantine_path.open("a", encoding="utf-8") as handle:
            for record in records:
                handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
            handle.flush()
            os.fsync(handle.fileno())

    def _fsync_dir(self) -> None:
        if os.name == "nt":
            return
        fd = os.open(self.storage_dir, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


idempotency_store = OperationStore()
IdempotencyStore = OperationStore
