import json
from pathlib import Path
from typing import Any

from .audit import audit_service
from .config import settings
from .persistence import JsonlStore
from .trade_history import TradeHistoryStore, trade_history_store
from .trade_state import Trade


class AnalyticsStorage:
    def __init__(
        self,
        storage_dir: Path = settings.storage_dir,
        trade_history: TradeHistoryStore = trade_history_store,
        jsonl_store: JsonlStore | None = None,
    ):
        self.storage_dir = storage_dir
        self.trade_history = trade_history
        self.jsonl_store = jsonl_store or JsonlStore(storage_dir)
        self.audit_path = storage_dir / settings.audit_log_file
        self.cache_path = storage_dir / "analytics_cache.json"
        self.export_dir = storage_dir / "exports"

    def load_trades(self) -> list[Trade]:
        return list(self.trade_history.load_latest_trades().values())

    def load_trade_history(self) -> list[dict[str, Any]]:
        return self._iter_jsonl(self.trade_history.history_path)

    def load_delivery_history(self) -> list[dict[str, Any]]:
        return self._iter_jsonl(self.jsonl_store.delivery_history_path)

    def load_audit_history(self) -> list[dict[str, Any]]:
        return self._iter_jsonl(self.audit_path)

    def read_cache(self) -> dict[str, Any] | None:
        if not self.cache_path.exists():
            return None
        try:
            payload = json.loads(self.cache_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None
        return payload if isinstance(payload, dict) else None

    def write_cache(self, payload: dict[str, Any]) -> None:
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.cache_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def write_export(self, filename: str, content: str) -> Path:
        self.export_dir.mkdir(parents=True, exist_ok=True)
        path = self.export_dir / filename
        path.write_text(content, encoding="utf-8")
        audit_service.record("analytics_export_created", "analytics", path=str(path))
        return path

    def source_fingerprint(self) -> dict[str, float | int]:
        paths = [
            self.trade_history.snapshot_path,
            self.trade_history.history_path,
            self.jsonl_store.delivery_history_path,
            self.audit_path,
        ]
        size = 0
        latest_mtime = 0.0
        for path in paths:
            if path.exists():
                stat = path.stat()
                size += stat.st_size
                latest_mtime = max(latest_mtime, stat.st_mtime)
        return {"size": size, "latest_mtime": latest_mtime}

    def _iter_jsonl(self, path: Path) -> list[dict[str, Any]]:
        if not path.exists():
            return []
        records: list[dict[str, Any]] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                records.append(payload)
        return records


analytics_storage = AnalyticsStorage()
