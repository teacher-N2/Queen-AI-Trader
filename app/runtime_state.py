import asyncio
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from threading import RLock


@dataclass
class RuntimeState:
    initialized: bool = False
    accepting_work: bool = False
    started_at: str | None = None
    shutdown_at: str | None = None
    recovery_report: dict = field(default_factory=dict)
    degraded_reasons: list[str] = field(default_factory=list)
    active_operations: int = 0
    completed_operations: int = 0
    failed_operations: int = 0


class RuntimeStateManager:
    def __init__(self) -> None:
        self._lock = RLock()
        self.state = RuntimeState()

    def mark_started(self, recovery_report: dict) -> None:
        with self._lock:
            self.state.initialized = True
            self.state.accepting_work = True
            self.state.started_at = datetime.now(UTC).isoformat()
            self.state.recovery_report = recovery_report
            self.state.degraded_reasons = list(recovery_report.get("degraded_reasons", []))

    def mark_shutting_down(self) -> None:
        with self._lock:
            self.state.accepting_work = False
            self.state.shutdown_at = datetime.now(UTC).isoformat()

    @contextmanager
    def operation(self):
        self.begin_operation()
        try:
            yield
            self.complete_operation()
        except Exception:
            self.fail_operation()
            raise

    def begin_operation(self) -> None:
        with self._lock:
            self.state.active_operations += 1

    def complete_operation(self) -> None:
        with self._lock:
            self.state.active_operations = max(self.state.active_operations - 1, 0)
            self.state.completed_operations += 1

    def fail_operation(self) -> None:
        with self._lock:
            self.state.active_operations = max(self.state.active_operations - 1, 0)
            self.state.failed_operations += 1

    async def drain(self, timeout_seconds: float) -> dict:
        started = datetime.now(UTC)
        while True:
            with self._lock:
                active = self.state.active_operations
            if active == 0:
                return {"status": "drained", "pending": 0}
            if (datetime.now(UTC) - started).total_seconds() >= timeout_seconds:
                return {"status": "timeout", "pending": active}
            await asyncio.sleep(0.05)

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "initialized": self.state.initialized,
                "accepting_work": self.state.accepting_work,
                "started_at": self.state.started_at,
                "shutdown_at": self.state.shutdown_at,
                "recovery_report": self.state.recovery_report,
                "degraded_reasons": list(self.state.degraded_reasons),
                "active_operations": self.state.active_operations,
                "completed_operations": self.state.completed_operations,
                "failed_operations": self.state.failed_operations,
            }


runtime_state = RuntimeStateManager()
