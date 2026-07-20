from datetime import UTC, datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from .models import Direction, Target


class TradeLifecycleState(str, Enum):
    CREATED = "CREATED"
    QUALIFIED = "QUALIFIED"
    ENTRY_READY = "ENTRY_READY"
    ENTRY_EXECUTED = "ENTRY_EXECUTED"
    OPEN = "OPEN"
    PARTIAL_EXIT = "PARTIAL_EXIT"
    BREAK_EVEN = "BREAK_EVEN"
    STOP_UPDATED = "STOP_UPDATED"
    TARGET_1 = "TARGET_1"
    TARGET_2 = "TARGET_2"
    TARGET_3 = "TARGET_3"
    STOPPED = "STOPPED"
    INVALIDATED = "INVALIDATED"
    EXPIRED = "EXPIRED"
    CLOSED = "CLOSED"


TERMINAL_STATES = {
    TradeLifecycleState.STOPPED,
    TradeLifecycleState.INVALIDATED,
    TradeLifecycleState.EXPIRED,
    TradeLifecycleState.CLOSED,
}

CLOSED_STATES = {TradeLifecycleState.CLOSED}


class TradeTransitionRecord(BaseModel):
    timestamp: str
    previous_state: TradeLifecycleState | None
    new_state: TradeLifecycleState
    reason: str
    source_event: str
    source_event_id: str
    request_id: str | None = None
    correlation_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class Trade(BaseModel):
    trade_id: str
    signal_id: str
    setup_id: str | None = None
    entry_id: str | None = None
    symbol: str
    timeframe: str
    direction: Direction
    entry_price: float | None = None
    stop_price: float | None = None
    targets: list[Target] = Field(default_factory=list)
    remaining_position: float | None = None
    session: str | None = None
    created_at: str
    updated_at: str
    current_state: TradeLifecycleState
    state_history: list[TradeTransitionRecord] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    transition_count: int = 0
    final_disposition: TradeLifecycleState | None = None
    consumed_event_ids: list[str] = Field(default_factory=list)

    @classmethod
    def create(
        cls,
        *,
        trade_id: str,
        signal_id: str,
        setup_id: str | None,
        entry_id: str | None,
        symbol: str,
        timeframe: str,
        direction: Direction,
        entry_price: float | None,
        stop_price: float | None,
        targets: list[Target],
        remaining_position: float | None,
        session: str | None,
        initial_state: TradeLifecycleState,
        metadata: dict[str, Any] | None = None,
    ) -> "Trade":
        now = datetime.now(UTC).isoformat()
        return cls(
            trade_id=trade_id,
            signal_id=signal_id,
            setup_id=setup_id,
            entry_id=entry_id,
            symbol=symbol,
            timeframe=timeframe,
            direction=direction,
            entry_price=entry_price,
            stop_price=stop_price,
            targets=targets,
            remaining_position=remaining_position,
            session=session,
            created_at=now,
            updated_at=now,
            current_state=initial_state,
            metadata=metadata or {},
        )
