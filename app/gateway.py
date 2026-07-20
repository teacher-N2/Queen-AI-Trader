import time
import uuid
from typing import Any

from fastapi import Request

from .audit import audit_service
from .auth import auth_service
from .delivery import delivery_engine
from .idempotency import WebhookOperationState, idempotency_store
from .message_builder import message_builder
from .metrics import metrics
from .models import QueenSignalPayload
from .operations import operations_service
from .persistence import store
from .replay import replay_service
from .retry_policy import NON_RETRYABLE
from .routing import routing_service
from .trade_events import trade_state_engine
from .validation import validation_service
from .runtime_context import update_context
from .runtime_state import runtime_state


class QueenGateway:
    async def handle_tradingview(self, request: Request) -> dict[str, Any]:
        with runtime_state.operation():
            return await self._handle_tradingview(request)

    async def _handle_tradingview(self, request: Request) -> dict[str, Any]:
        started = time.perf_counter()
        request_id = request.headers.get("x-request-id", str(uuid.uuid4()))
        raw_body = await request.body()

        audit_service.record("webhook_received", request_id, path=str(request.url.path), body_size=len(raw_body))
        auth_service.authenticate(request, raw_body)
        audit_service.record("authentication_succeeded", request_id)

        payload = validation_service.parse_json(raw_body)
        if operations_service.is_canonical_payload(payload):
            return await operations_service.process_payload(
                payload,
                request_id=request_id,
                source_key=request.client.host if request.client else "tradingview",
            )
        signals = self._expand_payload(payload)
        results: list[dict[str, Any]] = []

        for signal_payload in signals:
            signal = validation_service.validate(signal_payload)
            update_context(signal_id=signal.signal_id, trade_id=signal.trade_id, event_id=signal.event_id)
            metrics.increment("signals_received_total")
            replay_key = replay_service.replay_key(signal)
            action, stored_result = idempotency_store.begin_webhook(replay_key, signal_payload)
            if action == "completed" and stored_result:
                results.append(stored_result)
                continue
            if action == "permanent" and stored_result:
                results.append(stored_result)
                continue
            if action == "active":
                results.append(
                    {
                        "signal_id": signal.signal_id,
                        "event": signal.event.value,
                        "route": "processing",
                        "delivery": {"status": "processing"},
                    }
                )
                continue
            try:
                audit_service.record(
                    "validation_succeeded",
                    request_id,
                    signal_id=signal.signal_id,
                    trade_id=signal.trade_id,
                    event=signal.event.value,
                )

                correlation_id = signal.signal_id
                trade = trade_state_engine.consume_signal(signal, request_id=request_id, correlation_id=correlation_id)
                audit_service.record(
                    "trade_state_consumed",
                    request_id,
                    signal_id=signal.signal_id,
                    trade_id=trade.trade_id if trade else signal.trade_id,
                    state=trade.current_state.value if trade else None,
                )

                routed = routing_service.route(signal, correlation_id)
                audit_service.record(
                    "routing_completed",
                    request_id,
                    signal_id=signal.signal_id,
                    trade_id=signal.trade_id,
                    route=routed.route,
                    destination_count=len(routed.destinations),
                )

                message = message_builder.build(routed)
                audit_service.record("message_created", request_id, signal_id=signal.signal_id, route=routed.route)

                delivery = await delivery_engine.deliver(routed, message, request_id)
                safe_result = {
                    "signal_id": signal.signal_id,
                    "event": signal.event.value,
                    "route": routed.route,
                    "delivery": delivery.model_dump(),
                }
                store.save_processed_signal(
                    {
                        "request_id": request_id,
                        "replay_key": replay_key,
                        "signal_id": signal.signal_id,
                        "event_id": signal.event_id,
                        "trade_id": signal.trade_id,
                        "event": signal.event.value,
                        "route": routed.route,
                        "delivery_status": delivery.status,
                    }
                )
                idempotency_store.mark_webhook(replay_key, WebhookOperationState.COMPLETED, result=safe_result)
                audit_service.record(
                    "webhook_completed",
                    request_id,
                    signal_id=signal.signal_id,
                    trade_id=signal.trade_id,
                    delivery_status=delivery.status,
                )
                results.append(safe_result)
            except Exception as exc:
                state = WebhookOperationState.FAILED_PERMANENT if isinstance(exc, NON_RETRYABLE) else WebhookOperationState.FAILED_RETRYABLE
                idempotency_store.mark_webhook(
                    replay_key,
                    state,
                    result={
                        "signal_id": signal.signal_id,
                        "event": signal.event.value,
                        "route": "failed",
                        "delivery": {"status": state.value.lower()},
                    },
                    error=str(exc),
                )
                raise

        return {
            "accepted": True,
            "request_id": request_id,
            "event_count": len(results),
            "processing_ms": round((time.perf_counter() - started) * 1000, 2),
            "results": results,
        }

    def _expand_payload(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        if payload.get("event") != "SIGNAL_BATCH":
            return [payload]
        children = payload.get("events")
        if not isinstance(children, list) or not children:
            return [payload]
        expanded: list[dict[str, Any]] = []
        for index, child in enumerate(children):
            if not isinstance(child, dict):
                continue
            expanded_child = {
                "schema_version": payload.get("schema_version"),
                "engine": payload.get("engine"),
                "engine_version": payload.get("engine_version", "2.0"),
                "symbol": payload.get("symbol"),
                "exchange": payload.get("exchange"),
                "timeframe": payload.get("timeframe"),
                "timestamp": payload.get("timestamp", payload.get("bar_time")),
                "payload_signature_version": payload.get("payload_signature_version", "shared-secret-v1"),
                **child,
            }
            expanded_child.setdefault("signal_id", f"{payload.get('signal_id', 'SIGNAL_BATCH')}|{index}")
            expanded_child.setdefault("event_id", child.get("source_event_id", child.get("event_id", expanded_child["signal_id"])))
            expanded.append(expanded_child)
        return expanded


queen_gateway = QueenGateway()
