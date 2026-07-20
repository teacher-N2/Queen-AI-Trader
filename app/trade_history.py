import json
from pathlib import Path
from threading import RLock
from typing import Any

from .config import settings
from .trade_state import Trade, TradeTransitionRecord


class TradeHistoryStore:
    def __init__(self, storage_dir: Path = settings.storage_dir):
        self.storage_dir = storage_dir
        self.snapshot_path = storage_dir / settings.trade_snapshot_file
        self.history_path = storage_dir / settings.trade_history_file
        self._lock = RLock()

    def save_trade(self, trade: Trade) -> None:
        self._append(self.snapshot_path, trade.model_dump(mode="json"))

    def save_transition(self, trade: Trade, transition: TradeTransitionRecord) -> None:
        self._append(
            self.history_path,
            {
                "trade_id": trade.trade_id,
                "signal_id": trade.signal_id,
                "setup_id": trade.setup_id,
                "entry_id": trade.entry_id,
                "symbol": trade.symbol,
                "session": trade.session,
                "current_state": trade.current_state.value,
                "transition": transition.model_dump(mode="json"),
                "transition_count": trade.transition_count,
                "final_disposition": trade.final_disposition.value if trade.final_disposition else None,
            },
        )

    def load_latest_trades(self) -> dict[str, Trade]:
        latest: dict[str, Trade] = {}
        for record in self._iter_records(self.snapshot_path):
            trade_id = record.get("trade_id")
            if not trade_id:
                continue
            try:
                latest[trade_id] = Trade.model_validate(record)
            except ValueError:
                continue
        return latest

    def load_trade_history(self, trade_id: str) -> list[dict[str, Any]]:
        return [record for record in self._iter_records(self.history_path) if record.get("trade_id") == trade_id]

    def _append(self, path: Path, payload: dict[str, Any]) -> None:
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        with self._lock:
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")

    def _iter_records(self, path: Path) -> list[dict[str, Any]]:
        if not path.exists():
            return []
        records: list[dict[str, Any]] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(record, dict):
                records.append(record)
        return records


trade_history_store = TradeHistoryStore()
