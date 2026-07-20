import asyncio
import hashlib
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

import app.operations as operations_module
from app.config import Settings
from app.idempotency import OperationStore
from app.models import DeliveryAttempt, DeliveryResult
from app.operations import (
    IntakeState,
    OperationsStore,
    PersonalOperationsService,
    RateLimiter,
    RejectionCode,
)
from app.trade_events import TradeStateEngine
from app.trade_history import TradeHistoryStore
from app.trade_registry import TradeRegistry
from app.trade_state import TradeLifecycleState


PINE_ENGINE_SHA256 = "56db258a57a0cbd02fae3c88d918ab7593835383f07a4b38997def44a53a1852"


class FakeDelivery:
    def __init__(self):
        self.calls = []

    async def deliver(self, routed_event, message, request_id):
        self.calls.append((routed_event, message, request_id))
        return DeliveryResult(
            delivered=True,
            status="delivered",
            attempts=[DeliveryAttempt(destination="[redacted]", attempt=1, status="delivered")],
        )


class PersonalOperationsTests(unittest.TestCase):
    def setUp(self):
        self.original_settings = operations_module.settings
        self.original_idempotency = operations_module.idempotency_store

    def tearDown(self):
        operations_module.settings = self.original_settings
        operations_module.idempotency_store = self.original_idempotency

    def make_service(self, tmpdir: str):
        settings = Settings(
            webhook_shared_secret="test-secret",
            telegram_enabled=True,
            telegram_default_chat_id="chat-default",
            telegram_scalp_chat_id="chat-scalp",
            personal_operations_mode=True,
            tradingview_allowed_symbols=(),
            tradingview_allowed_timeframes=(),
            tradingview_max_signal_age_seconds=180,
            tradingview_warn_signal_age_seconds=60,
            default_entry_deviation_percent=1.0,
            gold_entry_deviation_percent=1.0,
            signal_min_confidence=0,
        )
        operations_module.settings = settings
        operations_module.idempotency_store = OperationStore(Path(tmpdir) / "idempotency")
        history = TradeHistoryStore(Path(tmpdir) / "trades")
        registry = TradeRegistry(history)
        engine = TradeStateEngine(registry=registry, history_store=history)
        store = OperationsStore(Path(tmpdir) / "operations")
        delivery = FakeDelivery()
        service = PersonalOperationsService(store=store, trade_engine=engine, delivery=delivery, limiter=RateLimiter())
        return service, registry, delivery

    def payload(self, **overrides):
        now = datetime.now(UTC)
        payload = {
            "schema_version": "1.0",
            "event_type": "SIGNAL_OPEN",
            "source": "QUEEN_ENGINE",
            "secret": "test-secret",
            "alert_id": "alert-1",
            "signal_id": "signal-1",
            "trade_id": None,
            "symbol": "GOLD",
            "exchange": "OANDA",
            "timeframe": "5",
            "side": "BUY",
            "setup_type": "ICT_2022",
            "entry_type": "MARKET",
            "entry": 3378.40,
            "stop_loss": 3374.90,
            "take_profits": [
                {"level": 1, "price": 3382.00},
                {"level": 2, "price": 3385.50},
                {"level": 3, "price": 3390.20},
            ],
            "confidence": 87,
            "session": "LONDON",
            "direction_bias": "BULLISH",
            "signal_timestamp": now.isoformat().replace("+00:00", "Z"),
            "bar_timestamp": (now - timedelta(minutes=5)).isoformat().replace("+00:00", "Z"),
            "price_at_alert": 3378.60,
            "risk_percent": 1.0,
            "mode": "PAPER_SIGNAL",
            "metadata": {"chart_symbol": "{{ticker}}", "secret": "should-redact"},
        }
        payload.update(overrides)
        return payload

    def test_valid_signal_open_creates_trade_and_delivery(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            service, registry, delivery = self.make_service(tmpdir)
            result = asyncio.run(service.process_payload(self.payload(), request_id="req-1"))
            self.assertTrue(result["accepted"])
            self.assertEqual(result["trade_id"], "QAT-signal-1")
            trade = registry.find_trade("QAT-signal-1")
            self.assertEqual(trade.current_state, TradeLifecycleState.OPEN)
            self.assertEqual(trade.symbol, "XAUUSD")
            self.assertEqual(delivery.calls[0][0].destinations, ["chat-scalp"])
            self.assertNotIn("test-secret", delivery.calls[0][1].body)

    def test_heartbeat_is_accepted_without_trade_creation(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            service, registry, delivery = self.make_service(tmpdir)
            result = asyncio.run(service.process_payload(self.payload(event_type="HEARTBEAT", alert_id="hb-1", signal_id="hb-sig", symbol=None, timeframe=None, side=None, entry=None, stop_loss=None, take_profits=[]), request_id="req-1"))
            self.assertTrue(result["accepted"])
            self.assertEqual(result["status"], "heartbeat")
            self.assertEqual(registry.find_open_trades(), [])
            self.assertEqual(delivery.calls, [])
            self.assertEqual(service.status()["tradingview"]["status"], "CONNECTED")

    def test_invalid_secret_is_rejected_safely(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            service, _, _ = self.make_service(tmpdir)
            result = asyncio.run(service.process_payload(self.payload(secret="wrong"), request_id="req-1"))
            self.assertFalse(result["accepted"])
            self.assertEqual(result["rejection_code"], RejectionCode.INVALID_SECRET.value)

    def test_stale_signal_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            service, _, _ = self.make_service(tmpdir)
            old = (datetime.now(UTC) - timedelta(minutes=10)).isoformat().replace("+00:00", "Z")
            result = asyncio.run(service.process_payload(self.payload(signal_timestamp=old), request_id="req-1"))
            self.assertFalse(result["accepted"])
            self.assertEqual(result["rejection_code"], RejectionCode.STALE_SIGNAL.value)

    def test_future_signal_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            service, _, _ = self.make_service(tmpdir)
            future = (datetime.now(UTC) + timedelta(minutes=10)).isoformat().replace("+00:00", "Z")
            result = asyncio.run(service.process_payload(self.payload(signal_timestamp=future), request_id="req-1"))
            self.assertFalse(result["accepted"])
            self.assertEqual(result["rejection_code"], RejectionCode.FUTURE_SIGNAL.value)

    def test_excessive_entry_deviation_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            service, _, _ = self.make_service(tmpdir)
            result = asyncio.run(service.process_payload(self.payload(price_at_alert=3500), request_id="req-1"))
            self.assertFalse(result["accepted"])
            self.assertEqual(result["rejection_code"], RejectionCode.ENTRY_DEVIATION_TOO_HIGH.value)

    def test_disabled_timeframe_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            service, _, _ = self.make_service(tmpdir)
            operations_module.settings = Settings(webhook_shared_secret="test-secret", tradingview_allowed_timeframes=("15",), telegram_default_chat_id="chat-default", telegram_enabled=False)
            result = asyncio.run(service.process_payload(self.payload(), request_id="req-1"))
            self.assertFalse(result["accepted"])
            self.assertEqual(result["rejection_code"], RejectionCode.TIMEFRAME_DISABLED.value)

    def test_pause_persists_and_rejects_signal_open(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            service, _, _ = self.make_service(tmpdir)
            state = service.pause(actor="owner")
            self.assertEqual(state.intake_state, IntakeState.PAUSED)
            restarted = PersonalOperationsService(store=OperationsStore(Path(tmpdir) / "operations"), trade_engine=service.trade_engine, delivery=service.delivery, limiter=RateLimiter())
            self.assertEqual(restarted.store.load_state().intake_state, IntakeState.PAUSED)
            result = asyncio.run(restarted.process_payload(self.payload(), request_id="req-1"))
            self.assertFalse(result["accepted"])
            self.assertEqual(result["rejection_code"], RejectionCode.SIGNALS_PAUSED.value)

    def test_tp_and_sl_updates_use_trade_state_engine(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            service, registry, _ = self.make_service(tmpdir)
            asyncio.run(service.process_payload(self.payload(), request_id="req-1"))
            tp = self.payload(event_type="TP_HIT", alert_id="alert-tp", signal_id="signal-tp", trade_id="QAT-signal-1", side=None, entry=None, stop_loss=None, take_profits=[], target_level=1)
            tp_result = asyncio.run(service.process_payload(tp, request_id="req-2"))
            self.assertTrue(tp_result["accepted"])
            self.assertEqual(registry.find_trade("QAT-signal-1").current_state, TradeLifecycleState.TARGET_1)
            sl = self.payload(event_type="SL_HIT", alert_id="alert-sl", signal_id="signal-sl", trade_id="QAT-signal-1", side=None, entry=None, stop_loss=None, take_profits=[])
            sl_result = asyncio.run(service.process_payload(sl, request_id="req-3"))
            self.assertTrue(sl_result["accepted"])
            self.assertEqual(registry.find_trade("QAT-signal-1").current_state, TradeLifecycleState.STOPPED)

    def test_duplicate_signal_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            service, _, _ = self.make_service(tmpdir)
            asyncio.run(service.process_payload(self.payload(), request_id="req-1"))
            result = asyncio.run(service.process_payload(self.payload(alert_id="alert-2"), request_id="req-2"))
            self.assertFalse(result["accepted"])
            self.assertEqual(result["rejection_code"], RejectionCode.DUPLICATE_SIGNAL.value)

    def test_configuration_redacts_secrets(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            service, _, _ = self.make_service(tmpdir)
            config = service.configuration()
            self.assertEqual(config["secrets"], "[redacted]")
            self.assertNotIn("test-secret", str(config))

    def test_pine_script_hash_remains_unchanged(self):
        pine_path = Path(__file__).resolve().parents[1] / "pine" / "Queen_Engine_v2.pine"
        self.assertEqual(hashlib.sha256(pine_path.read_bytes()).hexdigest(), PINE_ENGINE_SHA256)


if __name__ == "__main__":
    unittest.main()
