import uuid
import time

from .config import settings
from .errors import RetryExceededError
from .idempotency import DeliveryOperationState, idempotency_store
from .metrics import metrics
from .models import DeliveryAttempt, DeliveryResult, MessageEnvelope, RoutedEvent
from .observability import log_event
from .persistence import store
from .retry_policy import RetryPolicy, default_retry_policy
from .runtime_context import update_context
from .telegram import telegram_service


class DeliveryEngine:
    def __init__(self, retry_policy: RetryPolicy = default_retry_policy) -> None:
        self.retry_policy = retry_policy

    async def deliver(self, routed_event: RoutedEvent, message: MessageEnvelope, request_id: str) -> DeliveryResult:
        delivery_id = f"delivery_{uuid.uuid4().hex}"
        update_context(delivery_id=delivery_id)
        metrics.increment("deliveries_total")
        attempts: list[DeliveryAttempt] = []
        delivered_any = False
        handled_any = False

        for destination in routed_event.destinations:
            idempotency_key = f"{routed_event.payload.event_id}|{destination}"
            operation_payload = {
                "delivery_operation_id": idempotency_key,
                "signal_id": routed_event.payload.signal_id,
                "event_id": routed_event.payload.event_id,
                "trade_id": routed_event.payload.trade_id,
                "correlation_id": routed_event.correlation_id,
                "route": routed_event.route,
                "destination": "[redacted]",
                "destination_private": destination,
                "message_body_private": message.body,
                "message_format": message.format,
                "body_hash": idempotency_store.fingerprint({"body": message.body}),
            }
            action, stored_result = idempotency_store.begin_delivery(idempotency_key, operation_payload)
            if action == "completed":
                attempts.append(DeliveryAttempt(destination="[redacted]", attempt=0, status="deduplicated"))
                delivered_any = True
                handled_any = True
                continue
            if action in {"active", "permanent"}:
                attempts.append(DeliveryAttempt(destination="[redacted]", attempt=0, status=action))
                handled_any = True
                continue

            try:
                result = await self.retry_policy.run(
                    lambda attempt_number: self._send_once(destination, message, attempts, attempt_number)
                )
                if result.get("sent"):
                    delivered_any = True
                    handled_any = True
                    metrics.increment("delivery_success_total")
                    final_result = {"status": "delivered", "delivery_id": delivery_id, "attempts": [attempt.model_dump() for attempt in attempts]}
                    idempotency_store.mark_delivery(idempotency_key, DeliveryOperationState.DELIVERED, result=final_result)
                    continue
                raise RetryExceededError(str(result.get("reason", "delivery failed")))
            except Exception as exc:
                retryable = self.retry_policy.retryable(exc)
                state = DeliveryOperationState.RETRY_SCHEDULED if retryable else DeliveryOperationState.DEAD_LETTERED
                idempotency_store.mark_delivery(
                    idempotency_key,
                    state,
                    error=str(exc),
                    next_retry_at=time.time() + settings.delivery_initial_backoff_seconds if retryable else None,
                )
                metrics.increment("delivery_failure_total")
                if not retryable:
                    self._dead_letter(routed_event, request_id, attempts, exc)
                log_event("delivery_failed", status=state.value, error_type=exc.__class__.__name__, error_message=str(exc))
                if not retryable:
                    continue

        status = "delivered" if delivered_any else "failed"
        result = DeliveryResult(delivered=delivered_any, status=status, attempts=attempts)
        store.save_delivery_history(
            {
                "request_id": request_id,
                "signal_id": routed_event.payload.signal_id,
                "trade_id": routed_event.payload.trade_id,
                "status": status,
                "attempts": [attempt.model_dump() for attempt in attempts],
            }
        )
        if not delivered_any and not handled_any and routed_event.destinations:
            raise RetryExceededError("delivery attempts exhausted")
        return result

    async def _send_once(self, destination: str, message: MessageEnvelope, attempts: list[DeliveryAttempt], attempt_number: int) -> dict:
        result = await telegram_service.send_message(destination, message)
        if result.get("sent"):
            attempts.append(DeliveryAttempt(destination="[redacted]", attempt=attempt_number, status="delivered"))
            return result
        attempts.append(
            DeliveryAttempt(
                destination="[redacted]",
                attempt=attempt_number,
                status="failed",
                error=str(result.get("reason", "unknown delivery failure")),
            )
        )
        raise RetryExceededError(str(result.get("reason", "unknown delivery failure")))

    def _dead_letter(self, routed_event: RoutedEvent, request_id: str, attempts: list[DeliveryAttempt], exc: Exception) -> None:
        metrics.increment("dead_letters_total")
        store.save_dead_letter(
            {
                "dead_letter_id": f"dead_{uuid.uuid4().hex}",
                "request_id": request_id,
                "correlation_id": routed_event.correlation_id,
                "original_event_id": routed_event.payload.event_id,
                "operation": "telegram_delivery",
                "signal_id": routed_event.payload.signal_id,
                "trade_id": routed_event.payload.trade_id,
                "route": routed_event.route,
                "destination": "[redacted]",
                "failure_reason": str(exc),
                "error_type": exc.__class__.__name__,
                "attempt_count": len([attempt for attempt in attempts if attempt.attempt > 0]) or settings.delivery_max_attempts,
                "replay_eligibility": "manual_review_required",
                "resolution_status": "open",
            }
        )


delivery_engine = DeliveryEngine()
