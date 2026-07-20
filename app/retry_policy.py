import asyncio
import random
import time
from dataclasses import dataclass
from typing import Awaitable, Callable, TypeVar

try:
    import httpx
except ModuleNotFoundError:
    httpx = None  # type: ignore[assignment]

from .config import settings
from .errors import AuthenticationError, ReplayError, ValidationError
from .metrics import metrics
from .observability import log_event
from .production_errors import RetryExhaustedError
from .trade_errors import DuplicateEventError, InvalidTransitionError, TradeAlreadyClosedError

T = TypeVar("T")


NON_RETRYABLE = (
    ValidationError,
    AuthenticationError,
    ReplayError,
    InvalidTransitionError,
    DuplicateEventError,
    TradeAlreadyClosedError,
)


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = settings.delivery_max_attempts
    initial_backoff_seconds: float = settings.delivery_initial_backoff_seconds
    max_backoff_seconds: float = settings.delivery_max_backoff_seconds
    jitter_seconds: float = settings.retry_jitter_seconds
    overall_timeout_seconds: float = settings.retry_overall_timeout_seconds
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep

    def retryable(self, exc: Exception) -> bool:
        if isinstance(exc, asyncio.CancelledError):
            raise exc
        if isinstance(exc, NON_RETRYABLE):
            return False
        if httpx is not None and isinstance(exc, httpx.HTTPStatusError):
            return exc.response.status_code == 429 or 500 <= exc.response.status_code < 600
        retryable_types = (OSError,) if httpx is None else (httpx.HTTPError, OSError)
        return isinstance(exc, retryable_types)

    def retry_after_seconds(self, exc: Exception) -> float | None:
        if httpx is None or not isinstance(exc, httpx.HTTPStatusError):
            return None
        if exc.response.status_code != 429:
            return None
        value = exc.response.headers.get("retry-after")
        if not value:
            return None
        try:
            return max(float(value), 0.0)
        except ValueError:
            return None

    async def run(self, operation: Callable[[int], Awaitable[T]]) -> T:
        started = time.monotonic()
        last_exc: Exception | None = None
        for attempt in range(1, self.max_attempts + 1):
            if time.monotonic() - started > self.overall_timeout_seconds:
                raise RetryExhaustedError("retry timeout budget exhausted")
            try:
                return await operation(attempt)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                last_exc = exc
                if attempt >= self.max_attempts or not self.retryable(exc):
                    raise
                metrics.increment("retries_total")
                retry_after = self.retry_after_seconds(exc)
                backoff = retry_after if retry_after is not None else min(self.initial_backoff_seconds * (2 ** (attempt - 1)), self.max_backoff_seconds)
                if self.jitter_seconds:
                    backoff += random.uniform(0, self.jitter_seconds)
                log_event(
                    "retry_scheduled",
                    operation="retry_policy",
                    retry_count=attempt,
                    error_type=exc.__class__.__name__,
                    error_message=str(exc),
                )
                await self.sleep(backoff)
        raise RetryExhaustedError(str(last_exc or "retry exhausted"))


default_retry_policy = RetryPolicy()
