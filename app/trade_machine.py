from datetime import UTC, datetime

from .metrics import metrics
from .trade_errors import (
    DuplicateEventError,
    InvalidTransitionError,
    StateConflictError,
    TradeAlreadyClosedError,
)
from .trade_state import CLOSED_STATES, TERMINAL_STATES, Trade, TradeLifecycleState, TradeTransitionRecord


ACTIVE_TO_TERMINAL = {
    TradeLifecycleState.STOPPED,
    TradeLifecycleState.INVALIDATED,
    TradeLifecycleState.EXPIRED,
}

VALID_TRANSITIONS: dict[TradeLifecycleState, set[TradeLifecycleState]] = {
    TradeLifecycleState.CREATED: {TradeLifecycleState.QUALIFIED, *ACTIVE_TO_TERMINAL},
    TradeLifecycleState.QUALIFIED: {TradeLifecycleState.ENTRY_READY, *ACTIVE_TO_TERMINAL},
    TradeLifecycleState.ENTRY_READY: {TradeLifecycleState.ENTRY_EXECUTED, *ACTIVE_TO_TERMINAL},
    TradeLifecycleState.ENTRY_EXECUTED: {TradeLifecycleState.OPEN, *ACTIVE_TO_TERMINAL},
    TradeLifecycleState.OPEN: {
        TradeLifecycleState.PARTIAL_EXIT,
        TradeLifecycleState.BREAK_EVEN,
        TradeLifecycleState.STOP_UPDATED,
        TradeLifecycleState.TARGET_1,
        *ACTIVE_TO_TERMINAL,
    },
    TradeLifecycleState.PARTIAL_EXIT: {
        TradeLifecycleState.BREAK_EVEN,
        TradeLifecycleState.STOP_UPDATED,
        TradeLifecycleState.TARGET_1,
        TradeLifecycleState.TARGET_2,
        TradeLifecycleState.TARGET_3,
        *ACTIVE_TO_TERMINAL,
    },
    TradeLifecycleState.BREAK_EVEN: {
        TradeLifecycleState.PARTIAL_EXIT,
        TradeLifecycleState.STOP_UPDATED,
        TradeLifecycleState.TARGET_1,
        TradeLifecycleState.TARGET_2,
        TradeLifecycleState.TARGET_3,
        *ACTIVE_TO_TERMINAL,
    },
    TradeLifecycleState.STOP_UPDATED: {
        TradeLifecycleState.PARTIAL_EXIT,
        TradeLifecycleState.BREAK_EVEN,
        TradeLifecycleState.TARGET_1,
        TradeLifecycleState.TARGET_2,
        TradeLifecycleState.TARGET_3,
        *ACTIVE_TO_TERMINAL,
    },
    TradeLifecycleState.TARGET_1: {
        TradeLifecycleState.PARTIAL_EXIT,
        TradeLifecycleState.BREAK_EVEN,
        TradeLifecycleState.STOP_UPDATED,
        TradeLifecycleState.TARGET_2,
        *ACTIVE_TO_TERMINAL,
    },
    TradeLifecycleState.TARGET_2: {
        TradeLifecycleState.PARTIAL_EXIT,
        TradeLifecycleState.BREAK_EVEN,
        TradeLifecycleState.STOP_UPDATED,
        TradeLifecycleState.TARGET_3,
        *ACTIVE_TO_TERMINAL,
    },
    TradeLifecycleState.TARGET_3: {TradeLifecycleState.CLOSED},
    TradeLifecycleState.STOPPED: {TradeLifecycleState.CLOSED},
    TradeLifecycleState.INVALIDATED: {TradeLifecycleState.CLOSED},
    TradeLifecycleState.EXPIRED: {TradeLifecycleState.CLOSED},
    TradeLifecycleState.CLOSED: set(),
}


class TradeStateMachine:
    def validate_transition(self, trade: Trade, new_state: TradeLifecycleState, source_event_id: str) -> None:
        if source_event_id in trade.consumed_event_ids:
            raise DuplicateEventError("trade event has already been consumed")
        if trade.current_state == new_state:
            raise DuplicateEventError("duplicate trade state transition")
        if trade.current_state in CLOSED_STATES:
            raise TradeAlreadyClosedError("closed trade cannot transition")
        if trade.current_state in TERMINAL_STATES and new_state != TradeLifecycleState.CLOSED:
            raise TradeAlreadyClosedError("terminal trade can only transition to CLOSED")
        if new_state not in VALID_TRANSITIONS[trade.current_state]:
            metrics.increment("invalid_transitions_total")
            raise InvalidTransitionError(f"invalid transition {trade.current_state.value} -> {new_state.value}")
        self._validate_lifecycle_guard(trade, new_state)

    def apply_transition(
        self,
        trade: Trade,
        *,
        new_state: TradeLifecycleState,
        reason: str,
        source_event: str,
        source_event_id: str,
        request_id: str | None,
        correlation_id: str | None,
        metadata: dict,
    ) -> TradeTransitionRecord:
        self.validate_transition(trade, new_state, source_event_id)
        previous_state = trade.current_state
        record = TradeTransitionRecord(
            timestamp=datetime.now(UTC).isoformat(),
            previous_state=previous_state,
            new_state=new_state,
            reason=reason,
            source_event=source_event,
            source_event_id=source_event_id,
            request_id=request_id,
            correlation_id=correlation_id,
            metadata=metadata,
        )
        trade.current_state = new_state
        trade.updated_at = record.timestamp
        trade.transition_count += 1
        trade.state_history.append(record)
        trade.consumed_event_ids.append(source_event_id)
        if new_state in TERMINAL_STATES:
            trade.final_disposition = new_state
        return record

    def _validate_lifecycle_guard(self, trade: Trade, new_state: TradeLifecycleState) -> None:
        if new_state == TradeLifecycleState.BREAK_EVEN and trade.current_state not in {
            TradeLifecycleState.OPEN,
            TradeLifecycleState.PARTIAL_EXIT,
            TradeLifecycleState.STOP_UPDATED,
            TradeLifecycleState.TARGET_1,
            TradeLifecycleState.TARGET_2,
        }:
            raise StateConflictError("BREAK_EVEN requires an open trade lifecycle")
        if new_state in {TradeLifecycleState.TARGET_1, TradeLifecycleState.TARGET_2, TradeLifecycleState.TARGET_3}:
            if trade.current_state in TERMINAL_STATES:
                raise StateConflictError("target cannot be applied after terminal state")
        if new_state == TradeLifecycleState.STOPPED and trade.current_state == TradeLifecycleState.CLOSED:
            raise TradeAlreadyClosedError("STOPPED cannot be applied after CLOSED")


trade_state_machine = TradeStateMachine()
