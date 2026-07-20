from .errors import ReplayError
from .metrics import metrics
from .models import QueenSignalPayload
from .persistence import store


class ReplayProtectionService:
    def replay_key(self, signal: QueenSignalPayload) -> str:
        return "|".join(
            [
                signal.signal_id,
                signal.event_id,
                signal.trade_id or "NONE",
                str(signal.timestamp),
            ]
        )

    def assert_not_replayed(self, signal: QueenSignalPayload) -> str:
        key = self.replay_key(signal)
        if store.signal_exists(key):
            metrics.increment("duplicate_events_total")
            raise ReplayError("duplicate webhook ignored")
        return key


replay_service = ReplayProtectionService()
