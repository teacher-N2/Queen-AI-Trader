import time
from datetime import UTC, datetime
from typing import Any

from .analytics_storage import analytics_storage
from .circuit_breaker import telegram_circuit_breaker
from .config import settings
from .runtime_state import runtime_state
from .telegram import telegram_service
from .trade_registry import trade_registry
from .operations import operations_service

_process_started = time.time()


class HealthService:
    def live(self) -> dict[str, Any]:
        return self._base("healthy", checks={"event_loop": {"status": "healthy"}})

    def ready(self) -> dict[str, Any]:
        checks: dict[str, dict[str, Any]] = {}
        degraded: list[str] = []
        state = runtime_state.snapshot()
        checks["runtime"] = {"status": "healthy" if state["initialized"] and state["accepting_work"] else "unhealthy"}
        recovery_report = state.get("recovery_report") or {}
        recovery_status = recovery_report.get("status", "unknown")
        checks["recovery"] = {
            "status": "degraded" if recovery_status == "degraded" else "healthy" if recovery_status in {"recovered", "healthy"} else "unhealthy",
            "pending_deliveries": recovery_report.get("pending_deliveries", 0),
            "stale_in_progress_deliveries": recovery_report.get("stale_in_progress_deliveries", 0),
            "retry_scheduled_deliveries": recovery_report.get("retry_scheduled_deliveries", 0),
            "corrupt_records_quarantined": recovery_report.get("corrupt_records_quarantined", 0),
            "open_dead_letters": recovery_report.get("open_dead_letters", 0),
            "recovery_failures": recovery_report.get("recovery_failures", 0),
        }
        checks["configuration"] = self._config_check()
        checks["persistence"] = self._path_check(settings.storage_dir)
        checks["trade_registry"] = {"status": "healthy", "open_trades": len(trade_registry.find_open_trades())}
        checks["analytics_storage"] = {"status": "healthy", "fingerprint": analytics_storage.source_fingerprint()}
        operations_status = operations_service.status()
        checks["personal_operations"] = {
            "status": "healthy",
            "mode": operations_status["mode"],
            "signal_intake": operations_status["system_status"],
            "tradingview": operations_status["tradingview"]["status"],
            "telegram": operations_status["telegram"]["status"],
        }
        telegram_status = "healthy" if telegram_service.configured() else "degraded"
        circuit = telegram_circuit_breaker.snapshot()
        if circuit["state"] == "OPEN":
            telegram_status = "degraded"
        checks["telegram"] = {"status": telegram_status, "circuit": circuit}
        if telegram_status == "degraded" and settings.telegram_enabled:
            degraded.append("telegram_not_configured")
        for name, check in checks.items():
            if check["status"] == "unhealthy":
                return self._base("unhealthy", checks=checks, degraded_reasons=degraded + [name])
            if check["status"] == "degraded":
                degraded.append(name)
        status = "degraded" if degraded else "healthy"
        return self._base(status, checks=checks, degraded_reasons=degraded)

    def _base(self, status: str, *, checks: dict[str, Any], degraded_reasons: list[str] | None = None) -> dict[str, Any]:
        return {
            "status": status,
            "service": settings.app_name,
            "version": settings.app_version,
            "environment": settings.environment,
            "uptime_seconds": round(time.time() - _process_started, 2),
            "timestamp": datetime.now(UTC).isoformat(),
            "checks": checks,
            "degraded_reasons": degraded_reasons or [],
        }

    def _config_check(self) -> dict[str, Any]:
        if settings.environment == "production" and not settings.webhook_shared_secret:
            return {"status": "unhealthy", "reason": "missing webhook secret"}
        if settings.environment == "production" and settings.debug:
            return {"status": "unhealthy", "reason": "debug enabled in production"}
        return {"status": "healthy"}

    def _path_check(self, path) -> dict[str, Any]:
        try:
            path.mkdir(parents=True, exist_ok=True)
            probe = path / ".readiness_probe"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink(missing_ok=True)
            return {"status": "healthy"}
        except OSError as exc:
            return {"status": "unhealthy", "reason": exc.__class__.__name__}


health_service = HealthService()
