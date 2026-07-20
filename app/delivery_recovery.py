import time

from .delivery import DeliveryEngine
from .idempotency import DeliveryOperationState, idempotency_store
from .models import Actionability, Direction, MessageEnvelope, QueenSignalPayload, RoutedEvent, SignalAction, SignalEvent
from .observability import log_event


class DeliveryRecoveryWorker:
    def __init__(self, engine: DeliveryEngine | None = None) -> None:
        self.engine = engine or DeliveryEngine()

    async def recover_once(self, *, limit: int = 25) -> dict:
        resumed = 0
        skipped = 0
        failed = 0
        now = time.time()
        for record in idempotency_store.recoverable_operations(include_private=True)[:limit]:
            if record.get("scope") != "delivery":
                continue
            state = record.get("state")
            if state == DeliveryOperationState.RETRY_SCHEDULED.value and float(record.get("next_retry_at") or 0) > now:
                skipped += 1
                continue
            payload = record.get("payload") or {}
            destination = payload.get("destination_private")
            body = payload.get("message_body_private")
            if not destination or not body:
                skipped += 1
                continue
            try:
                message = MessageEnvelope(
                    payload=self._payload(payload),
                    route=str(payload.get("route") or "recovery"),
                    format=payload.get("message_format") or "telegram_markdown",
                    body=body,
                )
                await self.engine.deliver(self._routed_event(payload, destination, message.payload), message, "recovery")
                resumed += 1
            except Exception as exc:
                failed += 1
                log_event("delivery_recovery_failed", status="failed", error_type=exc.__class__.__name__, error_message=str(exc))
        return {"resumed": resumed, "skipped": skipped, "failed": failed}

    def _payload(self, payload: dict) -> QueenSignalPayload:
        return QueenSignalPayload.model_validate(
            {
                "schema_version": "1.0",
                "engine": "Queen Engine",
                "engine_version": "2.0",
                "signal_id": payload.get("signal_id") or "recovered-signal",
                "event_id": payload.get("event_id") or payload.get("delivery_operation_id") or "recovered-event",
                "trade_id": payload.get("trade_id"),
                "timestamp": int(time.time() * 1000),
                "symbol": payload.get("symbol") or "UNKNOWN",
                "timeframe": payload.get("timeframe") or "UNKNOWN",
                "event": SignalEvent.INFORMATIONAL_SIGNAL,
                "direction": Direction.NEUTRAL,
                "action": SignalAction.NONE,
                "actionability": Actionability.INFORMATIONAL,
                "payload_signature_version": "recovery-v1",
            }
        )

    def _routed_event(self, payload: dict, destination: str, signal: QueenSignalPayload) -> RoutedEvent:
        return RoutedEvent(
            payload=signal,
            route=str(payload.get("route") or "recovery"),
            destinations=[destination],
            priority=0,
            correlation_id=str(payload.get("correlation_id") or "recovery"),
        )


delivery_recovery_worker = DeliveryRecoveryWorker()
