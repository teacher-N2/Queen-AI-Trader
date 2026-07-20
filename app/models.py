from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class Direction(str, Enum):
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    NEUTRAL = "NEUTRAL"


class Actionability(str, Enum):
    INFORMATIONAL = "INFORMATIONAL"
    PREPARATION = "PREPARATION"
    ACTIONABLE = "ACTIONABLE"
    MANAGEMENT = "MANAGEMENT"
    TERMINAL = "TERMINAL"


class SignalAction(str, Enum):
    NONE = "NONE"
    LONG = "LONG"
    SHORT = "SHORT"
    MOVE_STOP = "MOVE_STOP"
    MOVE_TO_BREAK_EVEN = "MOVE_TO_BREAK_EVEN"
    PARTIAL_CLOSE = "PARTIAL_CLOSE"
    TARGET_REACHED = "TARGET_REACHED"
    CLOSE_TRADE = "CLOSE_TRADE"
    CANCEL_TRADE = "CANCEL_TRADE"
    INVALIDATE_TRADE = "INVALIDATE_TRADE"


class SignalEvent(str, Enum):
    SIGNAL_BATCH = "SIGNAL_BATCH"
    SETUP_DETECTED_SIGNAL = "SETUP_DETECTED_SIGNAL"
    SETUP_QUALIFIED_SIGNAL = "SETUP_QUALIFIED_SIGNAL"
    ENTRY_READY_SIGNAL = "ENTRY_READY_SIGNAL"
    ENTRY_EXECUTED_SIGNAL = "ENTRY_EXECUTED_SIGNAL"
    TRADE_OPENED_SIGNAL = "TRADE_OPENED_SIGNAL"
    STOP_UPDATED_SIGNAL = "STOP_UPDATED_SIGNAL"
    BREAK_EVEN_SIGNAL = "BREAK_EVEN_SIGNAL"
    PARTIAL_EXIT_SIGNAL = "PARTIAL_EXIT_SIGNAL"
    TARGET_REACHED_SIGNAL = "TARGET_REACHED_SIGNAL"
    TRADE_STOPPED_SIGNAL = "TRADE_STOPPED_SIGNAL"
    TRADE_INVALIDATED_SIGNAL = "TRADE_INVALIDATED_SIGNAL"
    TRADE_EXPIRED_SIGNAL = "TRADE_EXPIRED_SIGNAL"
    TRADE_CLOSED_SIGNAL = "TRADE_CLOSED_SIGNAL"
    INFORMATIONAL_SIGNAL = "INFORMATIONAL_SIGNAL"
    WARNING_SIGNAL = "WARNING_SIGNAL"


class Target(BaseModel):
    name: str
    price: float


class QueenSignalPayload(BaseModel):
    schema_version: str
    engine: str
    engine_version: str
    signal_id: str
    event_id: str
    setup_id: str | None = None
    entry_id: str | None = None
    trade_id: str | None = None
    timestamp: int
    symbol: str
    exchange: str | None = None
    timeframe: str
    event: SignalEvent
    direction: Direction
    action: SignalAction
    actionability: Actionability
    entry_price: float | None = None
    stop_price: float | None = None
    targets: list[Target] = Field(default_factory=list)
    remaining_position: float | None = Field(default=None, ge=0)
    execution_window: str | None = None
    session: str | None = None
    reason_codes: list[str] = Field(default_factory=list)
    payload_signature_version: str
    message: str | None = None
    raw_payload: dict[str, Any] = Field(default_factory=dict, exclude=True)

    @model_validator(mode="before")
    @classmethod
    def normalize_aliases(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        normalized = dict(data)
        normalized.setdefault("schema_version", normalized.get("v"))
        normalized.setdefault("engine", "Queen Engine")
        normalized.setdefault("engine_version", "2.0")
        normalized.setdefault("signal_id", normalized.get("sid"))
        normalized.setdefault("event_id", normalized.get("src", normalized.get("source_event_id")))
        normalized.setdefault("setup_id", normalized.get("setup"))
        normalized.setdefault("entry_id", normalized.get("entry"))
        normalized.setdefault("trade_id", normalized.get("trade"))
        normalized.setdefault("timeframe", normalized.get("tf"))
        normalized.setdefault("direction", normalized.get("dir"))
        normalized.setdefault("stop_price", normalized.get("stop"))
        normalized.setdefault("timestamp", normalized.get("bar_time"))
        normalized.setdefault("remaining_position", normalized.get("remaining_position_pct"))
        normalized.setdefault("payload_signature_version", normalized.get("signature_version", "shared-secret-v1"))
        if "targets" not in normalized:
            targets: list[dict[str, Any]] = []
            for name, field_name in (("TP1", "tp1"), ("TP2", "tp2"), ("TP3", "tp3"), ("FINAL", "final_target")):
                value = normalized.get(field_name)
                if value is not None:
                    targets.append({"name": name, "price": value})
            normalized["targets"] = targets
        if not normalized.get("actionability") and normalized.get("event"):
            event = str(normalized["event"])
            if event in {"ENTRY_EXECUTED_SIGNAL", "TRADE_OPENED_SIGNAL"}:
                normalized["actionability"] = "ACTIONABLE"
            elif event in {"STOP_UPDATED_SIGNAL", "BREAK_EVEN_SIGNAL", "PARTIAL_EXIT_SIGNAL", "TARGET_REACHED_SIGNAL"}:
                normalized["actionability"] = "MANAGEMENT"
            elif event in {"TRADE_STOPPED_SIGNAL", "TRADE_INVALIDATED_SIGNAL", "TRADE_EXPIRED_SIGNAL", "TRADE_CLOSED_SIGNAL"}:
                normalized["actionability"] = "TERMINAL"
            elif event in {"SETUP_QUALIFIED_SIGNAL", "ENTRY_READY_SIGNAL"}:
                normalized["actionability"] = "PREPARATION"
            else:
                normalized["actionability"] = "INFORMATIONAL"
        normalized["raw_payload"] = data
        return normalized

    @field_validator("engine")
    @classmethod
    def validate_engine(cls, value: str) -> str:
        if value != "Queen Engine":
            raise ValueError("unsupported engine")
        return value

    @field_validator("signal_id", "event_id", "symbol", "timeframe")
    @classmethod
    def non_empty(cls, value: str) -> str:
        if not value:
            raise ValueError("field cannot be empty")
        return value


class RoutedEvent(BaseModel):
    payload: QueenSignalPayload
    route: str
    destinations: list[str]
    priority: int
    correlation_id: str


class MessageEnvelope(BaseModel):
    payload: QueenSignalPayload
    route: str
    format: Literal["telegram_markdown", "plain_text", "html", "discord", "email"]
    body: str


class DeliveryAttempt(BaseModel):
    destination: str
    attempt: int
    status: str
    error: str | None = None


class DeliveryResult(BaseModel):
    delivered: bool
    status: str
    attempts: list[DeliveryAttempt]


# Legacy models retained for older modules. The Phase 14 webhook path does not score or gate trades.
class TradingSignal(BaseModel):
    secret: str
    symbol: str = "XAUUSD"
    timeframe: str
    side: Literal["BUY", "SELL"]
    entry: float
    stop_loss: float
    take_profit_1: float
    take_profit_2: float | None = None
    take_profit_3: float | None = None
    liquidity_sweep: bool = False
    mss: bool = False
    fvg: bool = False
    order_block: bool = False
    session: Literal["ASIA", "LONDON", "NEW_YORK", "OTHER"] = "OTHER"
    rr: float = Field(ge=0)
    notes: str = ""


class ScoredSignal(BaseModel):
    signal: TradingSignal
    queen_score: int
    grade: str
    accepted: bool
    rejection_reason: str | None = None
