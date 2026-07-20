import json
import os
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock
from typing import Any

from .config import settings
from .observability import redact

JSONL_SCHEMA_VERSION = "jsonl-record-v1"


class JsonlStore:
    def __init__(self, storage_dir: Path = settings.storage_dir):
        self.storage_dir = storage_dir
        self.processed_signals_path = storage_dir / settings.processed_signals_file
        self.delivery_history_path = storage_dir / settings.delivery_history_file
        self.dead_letter_path = storage_dir / settings.dead_letter_file
        self.quarantine_path = storage_dir / "jsonl_quarantine.jsonl"
        self._lock = RLock()

    def _append(self, path: Path, payload: dict[str, Any]) -> None:
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        record = {"schema_version": JSONL_SCHEMA_VERSION, "created_at": datetime.now(UTC).isoformat(), **payload}
        with self._lock:
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
                handle.flush()
                os.fsync(handle.fileno())

    def _iter_records(self, path: Path) -> list[dict[str, Any]]:
        if not path.exists():
            return []
        records: list[dict[str, Any]] = []
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
                if isinstance(record, dict):
                    records.append(record)
                else:
                    raise ValueError("record is not a JSON object")
            except (json.JSONDecodeError, ValueError) as exc:
                self._quarantine(path, line_number, line, exc)
        return records

    def signal_exists(self, replay_key: str) -> bool:
        return any(record.get("replay_key") == replay_key for record in self._iter_records(self.processed_signals_path))

    def save_processed_signal(self, payload: dict[str, Any]) -> None:
        self._append(self.processed_signals_path, payload)

    def save_delivery_history(self, payload: dict[str, Any]) -> None:
        self._append(self.delivery_history_path, payload)

    def save_dead_letter(self, payload: dict[str, Any]) -> None:
        original_event_id = payload.get("original_event_id")
        operation = payload.get("operation")
        error_type = payload.get("error_type")
        for record in self._iter_records(self.dead_letter_path):
            if (
                record.get("original_event_id") == original_event_id
                and record.get("operation") == operation
                and record.get("error_type") == error_type
                and record.get("resolution_status", "open") == "open"
            ):
                return
        self._append(self.dead_letter_path, payload)

    def _quarantine(self, source: Path, line_number: int, raw_line: str, exc: Exception) -> None:
        payload = {
            "schema_version": JSONL_SCHEMA_VERSION,
            "created_at": datetime.now(UTC).isoformat(),
            "source_filename": str(source),
            "line_number": line_number,
            "timestamp": datetime.now(UTC).isoformat(),
            "error_type": exc.__class__.__name__,
            "raw_line": self._sanitize_raw_line(raw_line),
        }
        with self._lock:
            self.storage_dir.mkdir(parents=True, exist_ok=True)
            with self.quarantine_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")
                handle.flush()
                os.fsync(handle.fileno())

    def _sanitize_raw_line(self, raw_line: str) -> str:
        lowered = raw_line.lower()
        if any(marker in lowered for marker in ("secret", "token", "jwt", "api_key", "authorization", "signature", "credential", "password")):
            return "[redacted]"
        return raw_line[:500]


store = JsonlStore()
