import time
from enum import Enum
from threading import RLock

from .config import settings
from .metrics import metrics
from .production_errors import CircuitBreakerOpenError

try:
    import httpx
except ModuleNotFoundError:
    httpx = None  # type: ignore[assignment]


class CircuitState(str, Enum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


class CircuitBreaker:
    def __init__(
        self,
        name: str,
        failure_threshold: int = settings.circuit_failure_threshold,
        recovery_timeout_seconds: float = settings.circuit_recovery_timeout_seconds,
        half_open_probe_limit: int = settings.circuit_half_open_probe_limit,
        success_threshold: int = settings.circuit_success_threshold,
    ) -> None:
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout_seconds = recovery_timeout_seconds
        self.half_open_probe_limit = half_open_probe_limit
        self.success_threshold = success_threshold
        self._lock = RLock()
        self.state = CircuitState.CLOSED
        self.failures = 0
        self.successes = 0
        self.opened_at = 0.0
        self.half_open_probes = 0

    def before_call(self) -> None:
        with self._lock:
            if self.state == CircuitState.OPEN:
                if time.monotonic() - self.opened_at >= self.recovery_timeout_seconds:
                    self.state = CircuitState.HALF_OPEN
                    self.half_open_probes = 0
                    self.successes = 0
                else:
                    raise CircuitBreakerOpenError(f"{self.name} circuit breaker is open")
            if self.state == CircuitState.HALF_OPEN:
                if self.half_open_probes >= self.half_open_probe_limit:
                    raise CircuitBreakerOpenError(f"{self.name} circuit breaker is half-open")
                self.half_open_probes += 1

    def record_success(self) -> None:
        with self._lock:
            self.failures = 0
            if self.state == CircuitState.HALF_OPEN:
                self.successes += 1
                if self.successes >= self.success_threshold:
                    self.state = CircuitState.CLOSED
                    self.half_open_probes = 0
                    self.successes = 0

    def qualifying_failure(self, exc: Exception) -> bool:
        if httpx is not None and isinstance(exc, httpx.HTTPStatusError):
            return exc.response.status_code == 429 or 500 <= exc.response.status_code < 600
        if httpx is not None and isinstance(exc, httpx.HTTPError):
            return True
        return isinstance(exc, OSError)

    def record_failure(self, exc: Exception | None = None) -> None:
        if exc is not None and not self.qualifying_failure(exc):
            return
        with self._lock:
            if self.state == CircuitState.HALF_OPEN:
                self.state = CircuitState.OPEN
                self.opened_at = time.monotonic()
                self.failures += 1
                metrics.increment("circuit_breaker_open_total")
                return
            self.failures += 1
            if self.failures >= self.failure_threshold:
                self.state = CircuitState.OPEN
                self.opened_at = time.monotonic()
                metrics.increment("circuit_breaker_open_total")

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "name": self.name,
                "state": self.state.value,
                "failures": self.failures,
                "successes": self.successes,
            }


telegram_circuit_breaker = CircuitBreaker("telegram")
