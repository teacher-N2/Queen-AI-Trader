import tempfile
import unittest
from pathlib import Path

from app.models import Actionability, Direction, QueenSignalPayload, SignalAction, SignalEvent
from app.trade_errors import DuplicateEventError, InvalidTransitionError, TradeAlreadyClosedError
from app.trade_events import TradeStateEngine
from app.trade_history import TradeHistoryStore
from app.trade_registry import TradeRegistry
from app.trade_state import TradeLifecycleState


def signal(event: SignalEvent, event_id: str, **overrides):
    payload = {
        "schema_version": "1.0",
        "engine": "Queen Engine",
        "engine_version": "2.0",
        "signal_id": "sig-1",
        "event_id": event_id,
        "setup_id": "setup-1",
        "entry_id": "entry-1",
        "trade_id": "trade-1",
        "timestamp": 1784500000000,
        "symbol": "XAUUSD",
        "timeframe": "5m",
        "event": event,
        "direction": Direction.BULLISH,
        "action": SignalAction.NONE,
        "actionability": Actionability.INFORMATIONAL,
        "entry_price": 2400.0,
        "stop_price": 2390.0,
        "targets": [{"name": "TP1", "price": 2420.0}],
        "remaining_position": 100.0,
        "payload_signature_version": "shared-secret-v1",
    }
    payload.update(overrides)
    return QueenSignalPayload.model_validate(payload)


class TradeStateEngineTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.history = TradeHistoryStore(Path(self.tmpdir.name))
        self.registry = TradeRegistry(self.history)
        self.engine = TradeStateEngine(self.registry, self.history)

    def tearDown(self):
        self.tmpdir.cleanup()

    def consume(self, payload):
        return self.engine.consume_signal(payload, request_id="req-1", correlation_id="corr-1")

    def test_valid_open_to_targets_to_close(self):
        self.consume(signal(SignalEvent.SETUP_DETECTED_SIGNAL, "event-1"))
        self.consume(signal(SignalEvent.SETUP_QUALIFIED_SIGNAL, "event-2"))
        self.consume(signal(SignalEvent.ENTRY_READY_SIGNAL, "event-3"))
        self.consume(signal(SignalEvent.ENTRY_EXECUTED_SIGNAL, "event-4"))
        self.consume(signal(SignalEvent.TRADE_OPENED_SIGNAL, "event-5"))
        self.consume(signal(SignalEvent.TARGET_REACHED_SIGNAL, "event-6", raw_payload={"target": "TP1"}))
        self.consume(signal(SignalEvent.TARGET_REACHED_SIGNAL, "event-7", raw_payload={"target": "TP2"}))
        self.consume(signal(SignalEvent.TARGET_REACHED_SIGNAL, "event-8", raw_payload={"target": "TP3"}))
        trade = self.consume(signal(SignalEvent.TRADE_CLOSED_SIGNAL, "event-9"))
        self.assertEqual(trade.current_state, TradeLifecycleState.CLOSED)

    def test_invalid_backward_transition_is_rejected(self):
        self.consume(signal(SignalEvent.TRADE_OPENED_SIGNAL, "event-1"))
        with self.assertRaises(InvalidTransitionError):
            self.consume(signal(SignalEvent.ENTRY_READY_SIGNAL, "event-2"))

    def test_duplicate_event_is_rejected(self):
        self.consume(signal(SignalEvent.TRADE_OPENED_SIGNAL, "event-1"))
        with self.assertRaises(DuplicateEventError):
            self.consume(signal(SignalEvent.TARGET_REACHED_SIGNAL, "event-1"))

    def test_closed_trade_cannot_reopen(self):
        self.consume(signal(SignalEvent.TRADE_OPENED_SIGNAL, "event-1"))
        self.consume(signal(SignalEvent.TRADE_STOPPED_SIGNAL, "event-2"))
        self.consume(signal(SignalEvent.TRADE_CLOSED_SIGNAL, "event-3"))
        with self.assertRaises(TradeAlreadyClosedError):
            self.consume(signal(SignalEvent.TRADE_OPENED_SIGNAL, "event-4"))

    def test_restart_recovery_loads_latest_state(self):
        self.consume(signal(SignalEvent.TRADE_OPENED_SIGNAL, "event-1"))
        self.consume(signal(SignalEvent.TRADE_STOPPED_SIGNAL, "event-2"))
        recovered = TradeRegistry(self.history)
        self.assertEqual(recovered.find_trade("trade-1").current_state, TradeLifecycleState.STOPPED)


if __name__ == "__main__":
    unittest.main()
