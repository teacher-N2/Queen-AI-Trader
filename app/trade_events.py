from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from .audit import audit_service
from .concurrency import lock_manager
from .metrics import metrics
from .models import QueenSignalPayload, SignalEvent
from .trade_errors import StateConflictError, TradeNotFoundError
from .trade_history import TradeHistoryStore, trade_history_store
from .trade_machine import trade_state_machine
from .trade_registry import TradeRegistry, trade_registry
from .trade_state import Trade, TradeLifecycleState, TradeTransitionRecord


EVENT_TO_STATE: dict[SignalEvent, TradeLifecycleState] = {
    SignalEvent.SETUP_DETECTED_SIGNAL: TradeLifecycleState.CREATED,
    SignalEvent.SETUP_QUALIFIED_SIGNAL: TradeLifecycleState.QUALIFIED,
    SignalEvent.ENTRY_READY_SIGNAL: TradeLifecycleState.ENTRY_READY,
    SignalEvent.ENTRY_EXECUTED_SIGNAL: TradeLifecycleState.ENTRY_EXECUTED,
    SignalEvent.TRADE_OPENED_SIGNAL: TradeLifecycleState.OPEN,
    SignalEvent.STOP_UPDATED_SIGNAL: TradeLifecycleState.STOP_UPDATED,
    SignalEvent.BREAK_EVEN_SIGNAL: TradeLifecycleState.BREAK_EVEN,
    SignalEvent.PARTIAL_EXIT_SIGNAL: TradeLifecycleState.PARTIAL_EXIT,
    SignalEvent.TRADE_STOPPED_SIGNAL: TradeLifecycleState.STOPPED,
    SignalEvent.TRADE_INVALIDATED_SIGNAL: TradeLifecycleState.INVALIDATED,
    SignalEvent.TRADE_EXPIRED_SIGNAL: TradeLifecycleState.EXPIRED,
    SignalEvent.TRADE_CLOSED_SIGNAL: TradeLifecycleState.CLOSED,
}


@dataclass(frozen=True)
class TradeStateEvent:
    event_id: str
    trade_id: str
    source_event: SignalEvent
    target_state: TradeLifecycleState
    reason: str
    request_id: str | None
    correlation_id: str | None
    metadata: dict[str, Any] = field(default_factory=dict)


class TradeEventMapper:
    def from_signal(
        self,
        signal: QueenSignalPayload,
        *,
        request_id: str | None,
        correlation_id: str | None,
        current_trade: Trade | None = None,
    ) -> TradeStateEvent | None:
        target_state = self._target_state(signal, current_trade)
        if not target_state:
            return None
        return TradeStateEvent(
            event_id=signal.event_id,
            trade_id=self._trade_id(signal),
            source_event=signal.event,
            target_state=target_state,
            reason=signal.message or signal.event.value,
            request_id=request_id,
            correlation_id=correlation_id,
            metadata=self._metadata(signal),
        )

    def _target_state(self, signal: QueenSignalPayload, current_trade: Trade | None) -> TradeLifecycleState | None:
        if signal.event == SignalEvent.TARGET_REACHED_SIGNAL:
            return self._target_from_payload(signal, current_trade)
        return EVENT_TO_STATE.get(signal.event)

    def _target_from_payload(
        self,
        signal: QueenSignalPayload,
        current_trade: Trade | None,
    ) -> TradeLifecycleState:
        raw_target = str(
            signal.raw_payload.get("target_name")
            or signal.raw_payload.get("target")
            or signal.raw_payload.get("target_hit")
            or signal.raw_payload.get("tp")
            or ""
        ).upper()
        if raw_target in {"1", "TP1", "TARGET_1", "TARGET1"}:
            return TradeLifecycleState.TARGET_1
        if raw_target in {"2", "TP2", "TARGET_2", "TARGET2"}:
            return TradeLifecycleState.TARGET_2
        if raw_target in {"3", "TP3", "TARGET_3", "TARGET3", "FINAL"}:
            return TradeLifecycleState.TARGET_3
        if not current_trade:
            return TradeLifecycleState.TARGET_1
        if current_trade.current_state == TradeLifecycleState.TARGET_1:
            return TradeLifecycleState.TARGET_2
        if current_trade.current_state == TradeLifecycleState.TARGET_2:
            return TradeLifecycleState.TARGET_3
        return TradeLifecycleState.TARGET_1

    def _trade_id(self, signal: QueenSignalPayload) -> str:
        return signal.trade_id or signal.entry_id or signal.setup_id or signal.signal_id

    def _metadata(self, signal: QueenSignalPayload) -> dict[str, Any]:
        return {
            "entry_price": signal.entry_price,
            "stop_price": signal.stop_price,
            "remaining_position": signal.remaining_position,
            "reason_codes": signal.reason_codes,
            "action": signal.action.value,
            "actionability": signal.actionability.value,
        }


class TradeStateEngine:
    def __init__(
        self,
        registry: TradeRegistry = trade_registry,
        history_store: TradeHistoryStore = trade_history_store,
        mapper: TradeEventMapper | None = None,
    ):
        self.registry = registry
        self.history_store = history_store
        self.mapper = mapper or TradeEventMapper()

    def consume_signal(
        self,
        signal: QueenSignalPayload,
        *,
        request_id: str | None,
        correlation_id: str | None,
    ) -> Trade | None:
        trade_id = signal.trade_id or signal.entry_id or signal.setup_id or signal.signal_id
        with lock_manager.lock("trade_transition", trade_id):
            return self._consume_signal_locked(signal, trade_id=trade_id, request_id=request_id, correlation_id=correlation_id)

    def _consume_signal_locked(
        self,
        signal: QueenSignalPayload,
        *,
        trade_id: str,
        request_id: str | None,
        correlation_id: str | None,
    ) -> Trade | None:
        current_trade = self.registry.find_trade(trade_id) if self.registry.exists(trade_id) else None
        state_event = self.mapper.from_signal(
            signal,
            request_id=request_id,
            correlation_id=correlation_id,
            current_trade=current_trade,
        )
        if not state_event:
            return current_trade
        if not current_trade:
            current_trade = self._create_trade(signal, state_event)
            transition = self._initial_transition(current_trade, state_event)
            current_trade.state_history.append(transition)
            current_trade.transition_count = 1
            self.registry.upsert(current_trade)
            self.history_store.save_transition(current_trade, transition)
            audit_service.record(
                "trade_state_created",
                request_id or "",
                trade_id=current_trade.trade_id,
                correlation_id=correlation_id,
                state=current_trade.current_state.value,
                source_event=signal.event.value,
            )
            metrics.increment("trades_created_total")
            return current_trade
        transition = trade_state_machine.apply_transition(
            current_trade,
            new_state=state_event.target_state,
            reason=state_event.reason,
            source_event=state_event.source_event.value,
            source_event_id=state_event.event_id,
            request_id=state_event.request_id,
            correlation_id=state_event.correlation_id,
            metadata=state_event.metadata,
        )
        self._merge_signal_data(current_trade, signal)
        self.registry.upsert(current_trade)
        self.history_store.save_transition(current_trade, transition)
        audit_service.record(
            "trade_state_transition",
            request_id or "",
            trade_id=current_trade.trade_id,
            correlation_id=correlation_id,
            previous_state=transition.previous_state.value if transition.previous_state else None,
            new_state=transition.new_state.value,
            source_event=transition.source_event,
            source_event_id=transition.source_event_id,
        )
        metrics.increment("trade_transitions_total")
        return current_trade

    def _create_trade(self, signal: QueenSignalPayload, state_event: TradeStateEvent) -> Trade:
        if state_event.target_state not in {
            TradeLifecycleState.CREATED,
            TradeLifecycleState.QUALIFIED,
            TradeLifecycleState.ENTRY_READY,
            TradeLifecycleState.ENTRY_EXECUTED,
            TradeLifecycleState.OPEN,
        }:
            raise TradeNotFoundError("trade state event requires an existing trade")
        trade = Trade.create(
            trade_id=state_event.trade_id,
            signal_id=signal.signal_id,
            setup_id=signal.setup_id,
            entry_id=signal.entry_id,
            symbol=signal.symbol,
            timeframe=signal.timeframe,
            direction=signal.direction,
            entry_price=signal.entry_price,
            stop_price=signal.stop_price,
            targets=signal.targets,
            remaining_position=signal.remaining_position,
            session=signal.session,
            initial_state=state_event.target_state,
            metadata=state_event.metadata,
        )
        trade.consumed_event_ids.append(state_event.event_id)
        if state_event.target_state == TradeLifecycleState.OPEN and signal.entry_price is None:
            raise StateConflictError("OPEN trade requires entry_price")
        return trade

    def _initial_transition(self, trade: Trade, state_event: TradeStateEvent) -> TradeTransitionRecord:
        return TradeTransitionRecord(
            timestamp=datetime.now(UTC).isoformat(),
            previous_state=None,
            new_state=trade.current_state,
            reason=state_event.reason,
            source_event=state_event.source_event.value,
            source_event_id=state_event.event_id,
            request_id=state_event.request_id,
            correlation_id=state_event.correlation_id,
            metadata=state_event.metadata,
        )

    def _merge_signal_data(self, trade: Trade, signal: QueenSignalPayload) -> None:
        if signal.entry_price is not None:
            trade.entry_price = signal.entry_price
        if signal.stop_price is not None:
            trade.stop_price = signal.stop_price
        if signal.targets:
            trade.targets = signal.targets
        if signal.remaining_position is not None:
            trade.remaining_position = signal.remaining_position
        if signal.session:
            trade.session = signal.session
        if signal.entry_id and not trade.entry_id:
            trade.entry_id = signal.entry_id
        if signal.setup_id and not trade.setup_id:
            trade.setup_id = signal.setup_id


trade_state_engine = TradeStateEngine()
