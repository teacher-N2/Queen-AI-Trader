from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .config import settings
from .persistence import JsonlStore, store


class DeadLetterRegistry:
    def __init__(self, jsonl_store: JsonlStore = store):
        self.store = jsonl_store

    def find_by_id(self, dead_letter_id: str) -> dict[str, Any] | None:
        for record in self._records():
            if record.get("dead_letter_id") == dead_letter_id:
                return record
        return None

    def find_by_original_event_id(self, original_event_id: str) -> list[dict[str, Any]]:
        return [record for record in self._records() if record.get("original_event_id") == original_event_id]

    def find_open(self) -> list[dict[str, Any]]:
        return [record for record in self._records() if record.get("resolution_status", "open") == "open"]

    def find_resolved(self) -> list[dict[str, Any]]:
        return [record for record in self._records() if record.get("resolution_status") in {"resolved", "ignored", "manually_replayed"}]

    def mark_resolved(self, dead_letter_id: str) -> None:
        self._mark(dead_letter_id, "resolved")

    def mark_ignored(self, dead_letter_id: str) -> None:
        self._mark(dead_letter_id, "ignored")

    def mark_manually_replayed(self, dead_letter_id: str) -> None:
        self._mark(dead_letter_id, "manually_replayed")

    def _records(self) -> list[dict[str, Any]]:
        return self.store._iter_records(self.store.dead_letter_path)

    def _mark(self, dead_letter_id: str, status: str) -> None:
        records = self._records()
        for record in records:
            if record.get("dead_letter_id") == dead_letter_id:
                record["resolution_status"] = status
                record["resolved_at"] = datetime.now(UTC).isoformat()
        self._rewrite(records)

    def _rewrite(self, records: list[dict[str, Any]]) -> None:
        path: Path = self.store.dead_letter_path
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        with tmp.open("w", encoding="utf-8") as handle:
            import json
            import os

            for record in records:
                handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        tmp.replace(path)


dead_letter_registry = DeadLetterRegistry()
