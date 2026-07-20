import time
from collections import defaultdict
from threading import RLock
from typing import Any


class RuntimeMetrics:
    def __init__(self) -> None:
        self.started_at = time.time()
        self._lock = RLock()
        self._counters: dict[str, int] = defaultdict(int)
        self._durations: dict[str, list[float]] = defaultdict(list)
        self._gauges: dict[str, float] = defaultdict(float)

    def increment(self, name: str, amount: int = 1) -> None:
        with self._lock:
            self._counters[name] += amount

    def observe_duration(self, name: str, duration_ms: float) -> None:
        with self._lock:
            self._durations[name].append(duration_ms)
            self._durations[name] = self._durations[name][-1000:]

    def gauge(self, name: str, value: float) -> None:
        with self._lock:
            self._gauges[name] = value

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            durations = {
                name: {
                    "count": len(values),
                    "avg_ms": round(sum(values) / len(values), 4) if values else 0,
                    "max_ms": round(max(values), 4) if values else 0,
                }
                for name, values in self._durations.items()
            }
            return {
                "uptime_seconds": round(time.time() - self.started_at, 2),
                "counters": dict(self._counters),
                "durations": durations,
                "gauges": dict(self._gauges),
            }


metrics = RuntimeMetrics()
