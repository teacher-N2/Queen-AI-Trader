from pathlib import Path
from typing import Any
import os

from .analytics_storage import analytics_storage
from .config import settings
from .idempotency import idempotency_store
from .metrics import metrics
from .observability import log_event
from .dead_letters import dead_letter_registry
from .production_errors import RecoveryError
from .trade_registry import trade_registry


class RecoveryManager:
    def recover(self) -> dict[str, Any]:
        degraded_reasons: list[str] = []
        try:
            settings.storage_dir.mkdir(parents=True, exist_ok=True)
            self._quarantine_corrupt_jsonl(settings.storage_dir)
            trade_registry.recover()
            trades = trade_registry.find_open_trades() + trade_registry.find_closed_trades()
            analytics_storage.source_fingerprint()
            recoverable_operations = idempotency_store.recoverable_operations()
            pending_deliveries = [item for item in recoverable_operations if item.get("scope") == "delivery"]
            metrics.gauge("active_trades", len(trade_registry.find_open_trades()))
            corrupt_quarantined = self._quarantine_count(settings.storage_dir)
            report = {
                "status": "degraded" if pending_deliveries or corrupt_quarantined else "recovered",
                "trades_recovered": len({trade.trade_id for trade in trades}),
                "open_trades": len(trade_registry.find_open_trades()),
                "recoverable_operations": len(recoverable_operations),
                "recoverable_delivery_operations": len(pending_deliveries),
                "recoverable_webhook_operations": len([item for item in recoverable_operations if item.get("scope") == "webhook"]),
                "pending_deliveries": len([item for item in pending_deliveries if item.get("state") == "PENDING"]),
                "stale_in_progress_deliveries": len([item for item in pending_deliveries if item.get("state") == "IN_PROGRESS"]),
                "retry_scheduled_deliveries": len([item for item in pending_deliveries if item.get("state") == "RETRY_SCHEDULED"]),
                "corrupt_records_quarantined": corrupt_quarantined,
                "open_dead_letters": len(dead_letter_registry.find_open()),
                "recovery_failures": 0,
                "degraded_reasons": degraded_reasons,
            }
            log_event("recovery_completed", status="ok", operation="startup_recovery")
            return report
        except Exception as exc:
            metrics.increment("recovery_failures_total")
            log_event("recovery_failed", status="failed", error_type=exc.__class__.__name__, error_message=str(exc))
            raise RecoveryError("startup recovery failed") from exc

    def _quarantine_corrupt_jsonl(self, storage_dir: Path) -> None:
        for path in storage_dir.glob("*.jsonl"):
            if not path.exists():
                continue
            valid_lines: list[str] = []
            corrupt_lines: list[str] = []
            for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
                if not line.strip():
                    continue
                try:
                    import json

                    json.loads(line)
                    valid_lines.append(line)
                except json.JSONDecodeError:
                    corrupt_lines.append(
                        json.dumps(
                            {
                                "source_filename": str(path),
                                "line_number": line_number,
                                "timestamp": __import__("time").time(),
                                "error_type": "JSONDecodeError",
                                "raw_line": "[redacted]" if any(marker in line.lower() for marker in ("secret", "token", "jwt", "api_key", "authorization", "signature", "credential", "password")) else line[:500],
                            },
                            ensure_ascii=False,
                            separators=(",", ":"),
                        )
                    )
            if corrupt_lines:
                quarantine = path.with_suffix(path.suffix + ".quarantine")
                self._atomic_write(quarantine, "\n".join(corrupt_lines) + "\n", backup=False)
                self._atomic_write(path, "\n".join(valid_lines) + ("\n" if valid_lines else ""), backup=True)

    def _atomic_write(self, path: Path, content: str, *, backup: bool) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        if backup and path.exists():
            path.with_suffix(path.suffix + ".bak").write_bytes(path.read_bytes())
        tmp = path.with_suffix(path.suffix + ".tmp")
        with tmp.open("w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
        if os.name != "nt":
            fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)

    def _quarantine_count(self, storage_dir: Path) -> int:
        total = 0
        for path in storage_dir.glob("*.quarantine"):
            if path.exists():
                total += len([line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()])
        quarantine = storage_dir / "jsonl_quarantine.jsonl"
        if quarantine.exists():
            total += len([line for line in quarantine.read_text(encoding="utf-8").splitlines() if line.strip()])
        return total


recovery_manager = RecoveryManager()
