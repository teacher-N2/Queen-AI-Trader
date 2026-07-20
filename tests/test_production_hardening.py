import asyncio
import hashlib
import tempfile
import unittest
from pathlib import Path

try:
    import httpx
except ModuleNotFoundError:
    httpx = None  # type: ignore[assignment]

try:
    from fastapi.testclient import TestClient
except ModuleNotFoundError:
    TestClient = None  # type: ignore[assignment]

from app.circuit_breaker import CircuitBreaker, CircuitState
from app.config import Settings
from app.idempotency import DeliveryOperationState, IdempotencyStore
from app.dead_letters import DeadLetterRegistry
from app.delivery_recovery import DeliveryRecoveryWorker
from app.health import HealthService
from app.message_builder import message_builder
from app.models import Actionability, Direction, QueenSignalPayload, RoutedEvent, SignalAction, SignalEvent
from app.observability import redact
from app.persistence import JsonlStore
from app.production_errors import ConfigurationError, IdempotencyConflictError
from app.retry_policy import RetryPolicy
from app.runtime_context import RequestContext, get_context, reset_context, set_context
from app.runtime_state import RuntimeStateManager


class FakeTelegram:
    def __init__(self):
        self.calls = 0

    async def send_message(self, chat_id, message):
        self.calls += 1
        return {"sent": True}


class FailingOnceTelegram:
    def __init__(self):
        self.calls = 0

    async def send_message(self, chat_id, message):
        self.calls += 1
        if self.calls == 1:
            raise OSError("temporary telegram failure")
        return {"sent": True}


class SlowTelegram:
    def __init__(self):
        self.calls = 0
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def send_message(self, chat_id, message):
        self.calls += 1
        self.started.set()
        await self.release.wait()
        return {"sent": True}


class ProductionHardeningTests(unittest.TestCase):
    def test_redaction_removes_secrets(self):
        payload = {"webhook_secret": "secret-value", "nested": {"telegram_token": "token-value"}, "safe": "ok"}
        redacted = redact(payload)
        self.assertEqual(redacted["webhook_secret"], "[redacted]")
        self.assertEqual(redacted["nested"]["telegram_token"], "[redacted]")
        self.assertEqual(redacted["safe"], "ok")

    def test_request_context_is_context_local(self):
        token = set_context(RequestContext(request_id="req-a", correlation_id="corr-a"))
        try:
            self.assertEqual(get_context().request_id, "req-a")
            self.assertEqual(get_context().correlation_id, "corr-a")
        finally:
            reset_context(token)
        self.assertEqual(get_context().request_id, "unavailable")

    def test_idempotency_same_payload_and_conflict(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = IdempotencyStore(Path(tmpdir))
            self.assertIsNone(store.check_or_record("webhook", "key-1", {"a": 1}, {"status": "ok"}))
            self.assertEqual(store.check_or_record("webhook", "key-1", {"a": 1}), {"status": "ok"})
            with self.assertRaises(IdempotencyConflictError):
                store.check_or_record("webhook", "key-1", {"a": 2})

    def test_retry_policy_retries_then_succeeds(self):
        attempts = {"count": 0}

        async def operation(attempt):
            attempts["count"] = attempt
            if attempt < 2:
                raise OSError("temporary")
            return "ok"

        result = asyncio.run(RetryPolicy(max_attempts=3, initial_backoff_seconds=0, jitter_seconds=0).run(operation))
        self.assertEqual(result, "ok")
        self.assertEqual(attempts["count"], 2)

    def test_circuit_breaker_opens_and_half_opens(self):
        breaker = CircuitBreaker("test", failure_threshold=1, recovery_timeout_seconds=0, half_open_probe_limit=1)
        breaker.record_failure()
        self.assertEqual(breaker.state, CircuitState.OPEN)
        breaker.before_call()
        self.assertEqual(breaker.state, CircuitState.HALF_OPEN)
        breaker.record_success()
        self.assertEqual(breaker.state, CircuitState.CLOSED)

    def test_persistence_signal_exists(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = JsonlStore(Path(tmpdir))
            store.save_processed_signal({"replay_key": "abc"})
            self.assertTrue(store.signal_exists("abc"))

    def test_delivery_deduplicates_same_event(self):
        fake_telegram = FakeTelegram()
        calls = self._run_delivery_twice(fake_telegram)
        self.assertEqual(calls, 1)

    def test_delivery_failure_before_success_retries_and_sends(self):
        fake_telegram = FailingOnceTelegram()
        calls = self._run_single_delivery(fake_telegram)
        self.assertEqual(calls, 2)

    def test_restart_after_pending_delivery_retries(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = IdempotencyStore(Path(tmpdir))
            key, payload = self._delivery_key_payload()
            store.begin_delivery(key, payload)
            store.mark_delivery(key, DeliveryOperationState.PENDING)
            fake = FakeTelegram()
            self._run_single_delivery(fake, operation_store=IdempotencyStore(Path(tmpdir)))
            self.assertEqual(fake.calls, 1)

    def test_restart_after_stale_in_progress_delivery_retries(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = IdempotencyStore(Path(tmpdir))
            key, payload = self._delivery_key_payload()
            store.begin_delivery(key, payload)
            path = Path(tmpdir) / "idempotency_records.jsonl"
            text = path.read_text(encoding="utf-8").replace('"lease_expires_at":', '"lease_expires_at":0, "old_lease":')
            path.write_text(text, encoding="utf-8")
            fake = FakeTelegram()
            self._run_single_delivery(fake, operation_store=IdempotencyStore(Path(tmpdir)))
            self.assertEqual(fake.calls, 1)

    def test_delivered_delivery_never_resent_after_restart(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            first = FakeTelegram()
            self._run_single_delivery(first, operation_store=IdempotencyStore(Path(tmpdir)))
            second = FakeTelegram()
            self._run_single_delivery(second, operation_store=IdempotencyStore(Path(tmpdir)))
            self.assertEqual(first.calls, 1)
            self.assertEqual(second.calls, 0)

    def test_recovery_worker_sends_pending_delivery_once(self):
        import app.delivery as delivery_module
        import app.delivery_recovery as recovery_module

        with tempfile.TemporaryDirectory() as tmpdir:
            operation_store = IdempotencyStore(Path(tmpdir))
            key, payload = self._delivery_key_payload()
            operation_store.begin_delivery(key, payload)
            operation_store.mark_delivery(key, DeliveryOperationState.PENDING)
            fake = FakeTelegram()
            original_delivery_store = delivery_module.idempotency_store
            original_recovery_store = recovery_module.idempotency_store
            original_telegram = delivery_module.telegram_service
            original_store = delivery_module.store
            delivery_module.idempotency_store = operation_store
            recovery_module.idempotency_store = operation_store
            delivery_module.telegram_service = fake
            delivery_module.store = JsonlStore(Path(tmpdir))
            try:
                result = asyncio.run(DeliveryRecoveryWorker(delivery_module.DeliveryEngine()).recover_once())
                self.assertEqual(result["resumed"], 1)
                self.assertEqual(fake.calls, 1)
                result = asyncio.run(DeliveryRecoveryWorker(delivery_module.DeliveryEngine()).recover_once())
                self.assertEqual(result["resumed"], 0)
                self.assertEqual(fake.calls, 1)
            finally:
                delivery_module.idempotency_store = original_delivery_store
                recovery_module.idempotency_store = original_recovery_store
                delivery_module.telegram_service = original_telegram
                delivery_module.store = original_store

    def test_retry_scheduled_delivery_only_when_due(self):
        import app.delivery as delivery_module
        import app.delivery_recovery as recovery_module

        with tempfile.TemporaryDirectory() as tmpdir:
            operation_store = IdempotencyStore(Path(tmpdir))
            key, payload = self._delivery_key_payload()
            operation_store.begin_delivery(key, payload)
            operation_store.mark_delivery(key, DeliveryOperationState.RETRY_SCHEDULED, next_retry_at=9999999999)
            original_delivery_store = delivery_module.idempotency_store
            original_recovery_store = recovery_module.idempotency_store
            delivery_module.idempotency_store = operation_store
            recovery_module.idempotency_store = operation_store
            try:
                result = asyncio.run(DeliveryRecoveryWorker(delivery_module.DeliveryEngine()).recover_once())
                self.assertEqual(result["resumed"], 0)
                self.assertEqual(result["skipped"], 1)
            finally:
                delivery_module.idempotency_store = original_delivery_store
                recovery_module.idempotency_store = original_recovery_store

    def test_public_recoverable_operations_redact_private_delivery_fields(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            operation_store = IdempotencyStore(Path(tmpdir))
            key, payload = self._delivery_key_payload()
            operation_store.begin_delivery(key, payload)
            operation_store.mark_delivery(key, DeliveryOperationState.PENDING)
            public = operation_store.recoverable_operations()[0]
            self.assertNotIn("chat-1", str(public))
            self.assertNotIn("Queen Engine", str(public))

    def test_dead_letter_registry_deduplicates_and_resolves(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            jsonl_store = JsonlStore(Path(tmpdir))
            payload = {
                "dead_letter_id": "dead-1",
                "original_event_id": "event-1",
                "operation": "telegram_delivery",
                "error_type": "PermanentFailure",
                "resolution_status": "open",
            }
            jsonl_store.save_dead_letter(payload)
            jsonl_store.save_dead_letter({**payload, "dead_letter_id": "dead-2"})
            registry = DeadLetterRegistry(jsonl_store)
            self.assertEqual(len(registry.find_open()), 1)
            registry.mark_resolved("dead-1")
            self.assertEqual(len(registry.find_resolved()), 1)

    def test_readiness_degraded_for_pending_recovery_work(self):
        from app.runtime_state import runtime_state

        runtime_state.mark_started(
            {
                "status": "degraded",
                "pending_deliveries": 1,
                "stale_in_progress_deliveries": 0,
                "retry_scheduled_deliveries": 0,
                "corrupt_records_quarantined": 0,
                "open_dead_letters": 0,
                "recovery_failures": 0,
                "degraded_reasons": [],
            }
        )
        ready = HealthService().ready()
        self.assertIn(ready["status"], {"degraded", "unhealthy"})

    def test_two_simultaneous_delivery_requests_send_once(self):
        async def scenario():
            import app.delivery as delivery_module

            with tempfile.TemporaryDirectory() as tmpdir:
                original_idempotency = delivery_module.idempotency_store
                original_store = delivery_module.store
                original_telegram = delivery_module.telegram_service
                slow = SlowTelegram()
                delivery_module.idempotency_store = IdempotencyStore(Path(tmpdir))
                delivery_module.store = JsonlStore(Path(tmpdir))
                delivery_module.telegram_service = slow
                try:
                    routed = self._routed_event()
                    message = message_builder.build(routed)
                    engine = delivery_module.DeliveryEngine(RetryPolicy(max_attempts=1, initial_backoff_seconds=0, jitter_seconds=0))
                    first = asyncio.create_task(engine.deliver(routed, message, "req-1"))
                    await slow.started.wait()
                    second = asyncio.create_task(engine.deliver(routed, message, "req-1"))
                    await asyncio.sleep(0)
                    slow.release.set()
                    await asyncio.gather(first, second)
                    return slow.calls
                finally:
                    delivery_module.idempotency_store = original_idempotency
                    delivery_module.store = original_store
                    delivery_module.telegram_service = original_telegram

        self.assertEqual(asyncio.run(scenario()), 1)

    def test_gateway_processing_operation_is_recoverable(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = IdempotencyStore(Path(tmpdir))
            action, _ = store.begin_webhook("webhook-key", {"signal": "payload"})
            self.assertEqual(action, "started")
            recoverable = store.recoverable_operations()
            self.assertEqual(recoverable, [])
            path = Path(tmpdir) / "idempotency_records.jsonl"
            text = path.read_text(encoding="utf-8").replace('"lease_expires_at":', '"lease_expires_at":0, "old_lease":')
            path.write_text(text, encoding="utf-8")
            self.assertEqual(len(IdempotencyStore(Path(tmpdir)).recoverable_operations()), 1)

    def test_retry_overall_timeout(self):
        async def operation(attempt):
            raise OSError("temporary")

        with self.assertRaises(Exception):
            asyncio.run(RetryPolicy(max_attempts=3, initial_backoff_seconds=0, jitter_seconds=0, overall_timeout_seconds=0.000001).run(operation))

    def test_cancellation_propagates(self):
        async def operation(attempt):
            raise asyncio.CancelledError()

        with self.assertRaises(asyncio.CancelledError):
            asyncio.run(RetryPolicy(max_attempts=3, initial_backoff_seconds=0, jitter_seconds=0).run(operation))

    def test_corrupt_operation_record_is_quarantined(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "idempotency_records.jsonl"
            path.write_text("{bad json\n", encoding="utf-8")
            store = IdempotencyStore(Path(tmpdir))
            self.assertEqual(store.recoverable_operations(), [])
            quarantine = Path(tmpdir) / "idempotency_records.jsonl.quarantine"
            self.assertIn("line_number", quarantine.read_text(encoding="utf-8"))

    def test_startup_validation_rejects_unsafe_production_config(self):
        settings = Settings(environment="production", webhook_shared_secret="", telegram_enabled=False, allowed_hosts=("example.com",))
        with self.assertRaises(ConfigurationError):
            settings.validate_startup()

    def test_shutdown_drain_success_and_timeout(self):
        manager = RuntimeStateManager()
        manager.begin_operation()
        timeout = asyncio.run(manager.drain(0.01))
        self.assertEqual(timeout["status"], "timeout")
        manager.complete_operation()
        drained = asyncio.run(manager.drain(0.01))
        self.assertEqual(drained["status"], "drained")

    def test_pine_script_hash_can_be_computed_without_mutation(self):
        path = Path("pine/Queen_Engine_v2.pine")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        self.assertEqual(len(digest), 64)

    def test_telegram_400_does_not_open_circuit_when_httpx_available(self):
        if httpx is None:
            self.skipTest("httpx is not installed in the local runtime")
        response = httpx.Response(400, request=httpx.Request("POST", "https://example.test"))
        exc = httpx.HTTPStatusError("bad request", request=response.request, response=response)
        breaker = CircuitBreaker("test", failure_threshold=1)
        breaker.record_failure(exc)
        self.assertEqual(breaker.state, CircuitState.CLOSED)

    def test_telegram_500_can_open_circuit_when_httpx_available(self):
        if httpx is None:
            self.skipTest("httpx is not installed in the local runtime")
        response = httpx.Response(500, request=httpx.Request("POST", "https://example.test"))
        exc = httpx.HTTPStatusError("server error", request=response.request, response=response)
        breaker = CircuitBreaker("test", failure_threshold=1)
        breaker.record_failure(exc)
        self.assertEqual(breaker.state, CircuitState.OPEN)

    def test_half_open_failure_returns_to_open(self):
        breaker = CircuitBreaker("test", failure_threshold=1, recovery_timeout_seconds=0)
        breaker.record_failure(OSError("temporary"))
        breaker.before_call()
        breaker.record_failure(OSError("temporary"))
        self.assertEqual(breaker.state, CircuitState.OPEN)

    def test_half_open_success_closes(self):
        breaker = CircuitBreaker("test", failure_threshold=1, recovery_timeout_seconds=0)
        breaker.record_failure(OSError("temporary"))
        breaker.before_call()
        breaker.record_success()
        self.assertEqual(breaker.state, CircuitState.CLOSED)

    def _run_delivery_twice(self, fake_telegram):
        return self._run_single_delivery(fake_telegram, twice=True)

    def _run_single_delivery(self, fake_telegram, operation_store=None, twice=False):
        import app.delivery as delivery_module

        with tempfile.TemporaryDirectory() as tmpdir:
            original_idempotency = delivery_module.idempotency_store
            original_store = delivery_module.store
            original_telegram = delivery_module.telegram_service
            delivery_module.idempotency_store = operation_store or IdempotencyStore(Path(tmpdir))
            delivery_module.store = JsonlStore(Path(tmpdir))
            delivery_module.telegram_service = fake_telegram
            try:
                routed = self._routed_event()
                message = message_builder.build(routed)
                asyncio.run(delivery_module.DeliveryEngine().deliver(routed, message, "req-1"))
                if twice:
                    asyncio.run(delivery_module.DeliveryEngine().deliver(routed, message, "req-1"))
                return fake_telegram.calls
            finally:
                delivery_module.idempotency_store = original_idempotency
                delivery_module.store = original_store
                delivery_module.telegram_service = original_telegram

    def _routed_event(self):
        payload = QueenSignalPayload.model_validate(
            {
                "schema_version": "1.0",
                "engine": "Queen Engine",
                "engine_version": "2.0",
                "signal_id": "sig-delivery",
                "event_id": "event-delivery",
                "trade_id": "trade-delivery",
                "timestamp": 1784500000000,
                "symbol": "XAUUSD",
                "timeframe": "M5",
                "event": SignalEvent.TRADE_OPENED_SIGNAL,
                "direction": Direction.BULLISH,
                "action": SignalAction.LONG,
                "actionability": Actionability.ACTIONABLE,
                "entry_price": 2400,
                "payload_signature_version": "shared-secret-v1",
            }
        )
        return RoutedEvent(payload=payload, route="actionable", destinations=["chat-1"], priority=90, correlation_id="corr")

    def _delivery_key_payload(self):
        routed = self._routed_event()
        message = message_builder.build(routed)
        key = f"{routed.payload.event_id}|chat-1"
        payload = {
            "delivery_operation_id": key,
            "signal_id": routed.payload.signal_id,
            "event_id": routed.payload.event_id,
            "trade_id": routed.payload.trade_id,
            "correlation_id": routed.correlation_id,
            "route": routed.route,
            "destination": "[redacted]",
            "destination_private": "chat-1",
            "message_body_private": message.body,
            "message_format": message.format,
            "body_hash": IdempotencyStore(Path(tempfile.gettempdir())).fingerprint({"body": message.body}),
        }
        return key, payload

    def test_health_endpoints(self):
        if TestClient is None:
            self.skipTest("fastapi is not installed in the local runtime")
        from app.main import app

        with TestClient(app) as client:
            live = client.get("/health/live")
            ready = client.get("/health/ready")
            metrics = client.get("/metrics")
        self.assertEqual(live.status_code, 200)
        self.assertIn(ready.status_code, {200, 503})
        self.assertEqual(metrics.status_code, 200)

    def test_middleware_request_size_limit(self):
        if TestClient is None:
            self.skipTest("fastapi is not installed in the local runtime")
        from app.main import app

        with TestClient(app) as client:
            response = client.post("/webhook/tradingview", content=b"{}", headers={"content-length": "999999999"})
        self.assertEqual(response.status_code, 413)
        self.assertIn("x-request-id", response.headers)


if __name__ == "__main__":
    unittest.main()
