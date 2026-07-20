import hmac
import json
import os
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from threading import RLock
from typing import Any

from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator

from .audit import audit_service
from .config import settings
from .delivery import DeliveryEngine, delivery_engine
from .errors import AuthenticationError, ValidationError as GatewayValidationError
from .idempotency import WebhookOperationState, idempotency_store
from .metrics import metrics
from .models import Actionability, Direction, MessageEnvelope, QueenSignalPayload, RoutedEvent, SignalAction, SignalEvent, Target
from .observability import redact
from .platform.models import Principal
from .production_errors import ConfigurationError, IdempotencyConflictError
from .trade_events import TradeStateEngine, trade_state_engine
from .trade_registry import trade_registry
from .trade_state import TradeLifecycleState

OPERATIONS_SCHEMA_VERSION = "operations-v1"


class OperationsMode(str, Enum):
    DISABLED = "DISABLED"
    PAPER_SIGNAL = "PAPER_SIGNAL"
    LIVE_SIGNAL = "LIVE_SIGNAL"


class IntakeState(str, Enum):
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    MAINTENANCE = "MAINTENANCE"


class OperationsEventType(str, Enum):
    SIGNAL_OPEN = "SIGNAL_OPEN"
    TRADE_ACTIVATED = "TRADE_ACTIVATED"
    TP_HIT = "TP_HIT"
    SL_HIT = "SL_HIT"
    TRADE_CLOSED = "TRADE_CLOSED"
    TRADE_CANCELLED = "TRADE_CANCELLED"
    TRADE_EXPIRED = "TRADE_EXPIRED"
    HEARTBEAT = "HEARTBEAT"


class Side(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class SignalDecision(str, Enum):
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    WARNING = "WARNING"
    HEARTBEAT = "HEARTBEAT"


class RejectionCode(str, Enum):
    DUPLICATE_SIGNAL = "DUPLICATE_SIGNAL"
    DUPLICATE_ALERT = "DUPLICATE_ALERT"
    STALE_SIGNAL = "STALE_SIGNAL"
    FUTURE_SIGNAL = "FUTURE_SIGNAL"
    INVALID_SECRET = "INVALID_SECRET"
    SYMBOL_DISABLED = "SYMBOL_DISABLED"
    TIMEFRAME_DISABLED = "TIMEFRAME_DISABLED"
    CONFIDENCE_BELOW_THRESHOLD = "CONFIDENCE_BELOW_THRESHOLD"
    INVALID_PRICE_STRUCTURE = "INVALID_PRICE_STRUCTURE"
    ENTRY_DEVIATION_TOO_HIGH = "ENTRY_DEVIATION_TOO_HIGH"
    SYSTEM_MAINTENANCE = "SYSTEM_MAINTENANCE"
    SIGNALS_PAUSED = "SIGNALS_PAUSED"
    UNSUPPORTED_SCHEMA = "UNSUPPORTED_SCHEMA"
    INVALID_EVENT_TYPE = "INVALID_EVENT_TYPE"
    RATE_LIMITED = "RATE_LIMITED"
    VALIDATION_ERROR = "VALIDATION_ERROR"


class ConnectionStatus(str, Enum):
    CONNECTED = "CONNECTED"
    STALE = "STALE"
    NEVER_CONNECTED = "NEVER_CONNECTED"


class TelegramStatus(str, Enum):
    CONNECTED = "CONNECTED"
    DEGRADED = "DEGRADED"
    FAILED = "FAILED"
    DISABLED = "DISABLED"


class TakeProfit(BaseModel):
    level: int = Field(ge=1, le=10)
    price: float = Field(gt=0)


class CanonicalWebhookPayload(BaseModel):
    schema_version: str
    event_type: OperationsEventType
    source: str = "QUEEN_ENGINE"
    secret: str | None = None
    alert_id: str
    signal_id: str
    trade_id: str | None = None
    symbol: str | None = None
    exchange: str | None = None
    timeframe: str | None = None
    side: Side | None = None
    setup_type: str | None = None
    entry_type: str | None = None
    entry: float | None = None
    stop_loss: float | None = None
    take_profits: list[TakeProfit] = Field(default_factory=list)
    confidence: int | None = Field(default=None, ge=0, le=100)
    session: str | None = None
    direction_bias: str | None = None
    signal_timestamp: str | None = None
    bar_timestamp: str | None = None
    price_at_alert: float | None = None
    risk_percent: float | None = None
    mode: str | None = None
    trading_style: str | None = None
    target_level: int | None = Field(default=None, ge=1, le=10)
    close_price: float | None = None
    close_reason: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("alert_id", "signal_id")
    @classmethod
    def non_empty(cls, value: str) -> str:
        if not value or len(value) > 160:
            raise ValueError("identifier is required and must be 160 chars or fewer")
        return value

    @field_validator("source")
    @classmethod
    def supported_source(cls, value: str) -> str:
        if value != "QUEEN_ENGINE":
            raise ValueError("unsupported source")
        return value

    @model_validator(mode="after")
    def validate_required_by_event(self):
        if len(self.metadata) > settings.max_metadata_fields:
            raise ValueError("metadata has too many fields")
        if len(self.take_profits) > settings.max_take_profit_count:
            raise ValueError("too many take-profit levels")
        if self.event_type == OperationsEventType.HEARTBEAT:
            return self
        required = {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "signal_timestamp": self.signal_timestamp,
        }
        if self.event_type == OperationsEventType.SIGNAL_OPEN:
            required.update({"side": self.side, "entry": self.entry, "stop_loss": self.stop_loss})
        else:
            required.update({"trade_id": self.trade_id})
        missing = [name for name, value in required.items() if value in {None, ""}]
        if missing:
            raise ValueError(f"missing required fields: {', '.join(missing)}")
        return self


class SymbolProfile(BaseModel):
    canonical: str
    display_name: str
    aliases: list[str]
    asset_class: str
    decimal_precision: int
    point_unit: str
    enabled: bool = True
    routing_profile: str | None = None


class SignalRecord(BaseModel):
    signal_id: str
    alert_id: str
    schema_version: str
    source: str
    event_type: str
    symbol: str | None = None
    original_symbol: str | None = None
    timeframe: str | None = None
    side: str | None = None
    entry: float | None = None
    stop_loss: float | None = None
    take_profits: list[dict[str, Any]] = Field(default_factory=list)
    confidence: int | None = None
    session: str | None = None
    setup_type: str | None = None
    trading_style: str | None = None
    signal_timestamp: str | None = None
    received_at: str
    signal_age_seconds: float | None = None
    price_at_alert: float | None = None
    entry_deviation_percent: float | None = None
    decision: str
    rejection_code: str | None = None
    warning_code: str | None = None
    trade_id: str | None = None
    telegram_delivery_id: str | None = None
    mode: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class RejectionRecord(BaseModel):
    rejection_id: str = Field(default_factory=lambda: f"rej_{uuid.uuid4().hex}")
    signal_id: str | None = None
    alert_id: str | None = None
    event_type: str | None = None
    code: str
    message: str
    received_at: str
    retryable: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class OperationsState(BaseModel):
    schema_version: str = OPERATIONS_SCHEMA_VERSION
    mode: str = OperationsMode.PAPER_SIGNAL.value
    intake_state: IntakeState = IntakeState.RUNNING
    last_tradingview_heartbeat_at: str | None = None
    last_signal_received_at: str | None = None
    last_accepted_signal_at: str | None = None
    last_rejected_signal_at: str | None = None
    last_telegram_success_at: str | None = None
    last_telegram_failure_at: str | None = None
    last_trade_update_at: str | None = None
    recent_error: str | None = None
    updated_at: str | None = None


class OperationsStore:
    def __init__(self, storage_dir: Path = settings.storage_dir / "operations"):
        self.storage_dir = storage_dir
        self.state_path = storage_dir / "state.json"
        self.signals_path = storage_dir / "signals.json"
        self.rejections_path = storage_dir / "rejections.json"
        self.heartbeats_path = storage_dir / "heartbeats.json"
        self._lock = RLock()

    def load_state(self) -> OperationsState:
        with self._lock:
            if not self.state_path.exists():
                return OperationsState(mode=settings.paper_signal_mode)
            return OperationsState.model_validate(json.loads(self.state_path.read_text(encoding="utf-8")))

    def save_state(self, state: OperationsState) -> OperationsState:
        state.updated_at = now_iso()
        self._write_json(self.state_path, state.model_dump(mode="json"))
        return state

    def append_signal(self, record: SignalRecord) -> SignalRecord:
        records = self.list_signals(limit=settings.operations_history_limit)
        records.append(record)
        self._write_json(self.signals_path, [item.model_dump(mode="json") for item in records[-settings.operations_history_limit :]])
        return record

    def append_rejection(self, record: RejectionRecord) -> RejectionRecord:
        records = self.list_rejections(limit=settings.operations_history_limit)
        records.append(record)
        self._write_json(self.rejections_path, [item.model_dump(mode="json") for item in records[-settings.operations_history_limit :]])
        return record

    def append_heartbeat(self, payload: dict[str, Any]) -> None:
        records = self._read_list(self.heartbeats_path)
        records.append(redact(payload))
        self._write_json(self.heartbeats_path, records[-settings.operations_history_limit :])

    def list_signals(self, *, limit: int = 50, offset: int = 0) -> list[SignalRecord]:
        return [SignalRecord.model_validate(item) for item in self._read_list(self.signals_path)][offset : offset + limit]

    def list_rejections(self, *, limit: int = 50, offset: int = 0) -> list[RejectionRecord]:
        return [RejectionRecord.model_validate(item) for item in self._read_list(self.rejections_path)][offset : offset + limit]

    def find_signal(self, signal_id: str) -> SignalRecord | None:
        for record in self.list_signals(limit=settings.operations_history_limit):
            if record.signal_id == signal_id:
                return record
        return None

    def signal_exists(self, signal_id: str) -> bool:
        return self.find_signal(signal_id) is not None

    def alert_exists(self, alert_id: str) -> bool:
        return any(record.alert_id == alert_id for record in self.list_signals(limit=settings.operations_history_limit))

    def _read_list(self, path: Path) -> list[dict[str, Any]]:
        with self._lock:
            if not path.exists():
                return []
            value = json.loads(path.read_text(encoding="utf-8"))
            return value if isinstance(value, list) else []

    def _write_json(self, path: Path, payload: Any) -> None:
        with self._lock:
            self.storage_dir.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(path.suffix + ".tmp")
            with tmp.open("w", encoding="utf-8") as handle:
                handle.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, path)


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    normalized = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


class SymbolRegistry:
    def __init__(self, profiles: list[SymbolProfile] | None = None):
        self.profiles = profiles or default_symbol_profiles()
        self._aliases: dict[str, SymbolProfile] = {}
        for profile in self.profiles:
            self._aliases[profile.canonical.upper()] = profile
            for alias in profile.aliases:
                self._aliases[alias.upper()] = profile

    def normalize(self, symbol: str | None) -> SymbolProfile:
        if not symbol:
            raise OperationsRejection(RejectionCode.VALIDATION_ERROR, "symbol is required")
        cleaned = symbol.split(":")[-1].replace("/", "").replace("-", "").upper()
        profile = self._aliases.get(cleaned)
        if profile:
            return profile
        return SymbolProfile(
            canonical=cleaned,
            display_name=cleaned,
            aliases=[],
            asset_class="UNKNOWN",
            decimal_precision=2,
            point_unit="point",
            enabled=True,
        )


def default_symbol_profiles() -> list[SymbolProfile]:
    return [
        SymbolProfile(canonical="XAUUSD", display_name="Gold", aliases=["GOLD", "XAU", "OANDA:XAUUSD"], asset_class="GOLD", decimal_precision=2, point_unit="point", routing_profile="INTRADAY"),
        SymbolProfile(canonical="NAS100", display_name="Nasdaq", aliases=["US100", "NDX", "NAS", "NAS100USD"], asset_class="INDEX", decimal_precision=2, point_unit="point", routing_profile="INTRADAY"),
        SymbolProfile(canonical="XAGUSD", display_name="Silver", aliases=["SILVER", "XAG"], asset_class="METAL", decimal_precision=3, point_unit="point"),
        SymbolProfile(canonical="EURUSD", display_name="Euro Dollar", aliases=["EUR/USD"], asset_class="FOREX", decimal_precision=5, point_unit="pip"),
        SymbolProfile(canonical="GBPUSD", display_name="Pound Dollar", aliases=["GBP/USD"], asset_class="FOREX", decimal_precision=5, point_unit="pip"),
        SymbolProfile(canonical="BTCUSD", display_name="Bitcoin", aliases=["BTC", "BTC/USD"], asset_class="CRYPTO", decimal_precision=2, point_unit="point", routing_profile="SWING"),
    ]


class TimeframeRegistry:
    def normalize(self, timeframe: str | None) -> str:
        if not timeframe:
            raise OperationsRejection(RejectionCode.VALIDATION_ERROR, "timeframe is required")
        value = str(timeframe).strip().upper()
        aliases = {"1H": "60", "H1": "60", "4H": "240", "H4": "240", "1D": "D", "1W": "W"}
        return aliases.get(value, value)

    def trading_style(self, timeframe: str, payload_style: str | None = None, profile: SymbolProfile | None = None) -> str:
        if payload_style:
            return payload_style.upper()
        if timeframe in {"1", "3", "5"}:
            return "SCALP"
        if timeframe in {"15", "30", "60"}:
            return "INTRADAY"
        if timeframe in {"240", "D", "W"}:
            return "SWING"
        return (profile.routing_profile if profile and profile.routing_profile else "INTRADAY")


class OperationsRejection(Exception):
    def __init__(self, code: RejectionCode, message: str, *, retryable: bool = False):
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable


class RateLimiter:
    def __init__(self):
        self._hits: dict[str, list[float]] = {}
        self._lock = RLock()

    def allow(self, key: str, limit_per_minute: int, now: float | None = None) -> bool:
        if limit_per_minute <= 0:
            return True
        current = now or time.time()
        floor = current - 60
        with self._lock:
            hits = [hit for hit in self._hits.get(key, []) if hit >= floor]
            if len(hits) >= limit_per_minute:
                self._hits[key] = hits
                return False
            hits.append(current)
            self._hits[key] = hits
            return True


@dataclass
class OperationsResult:
    status: str
    signal_id: str | None = None
    trade_id: str | None = None
    rejection_code: str | None = None
    retryable: bool = False
    record: SignalRecord | None = None
    delivery_status: str | None = None


class PersonalOperationsService:
    def __init__(
        self,
        store: OperationsStore | None = None,
        symbol_registry: SymbolRegistry | None = None,
        timeframe_registry: TimeframeRegistry | None = None,
        trade_engine: TradeStateEngine = trade_state_engine,
        delivery: DeliveryEngine = delivery_engine,
        limiter: RateLimiter | None = None,
    ):
        self.store = store or OperationsStore()
        self.symbols = symbol_registry or SymbolRegistry()
        self.timeframes = timeframe_registry or TimeframeRegistry()
        self.trade_engine = trade_engine
        self.delivery = delivery
        self.limiter = limiter or RateLimiter()

    def is_canonical_payload(self, payload: dict[str, Any]) -> bool:
        return "event_type" in payload

    async def process_payload(self, payload: dict[str, Any], *, request_id: str, source_key: str = "webhook") -> dict[str, Any]:
        received_at = now_iso()
        audit_service.record("tradingview.webhook.received", request_id, body_size=len(json.dumps(redact(payload), default=str)))
        try:
            if not self.limiter.allow(f"webhook:{source_key}", settings.webhook_rate_limit_per_minute):
                raise OperationsRejection(RejectionCode.RATE_LIMITED, "webhook rate limit exceeded", retryable=True)
            parsed = CanonicalWebhookPayload.model_validate(payload)
            self._authenticate(parsed)
            if parsed.schema_version not in settings.allowed_schema_versions:
                raise OperationsRejection(RejectionCode.UNSUPPORTED_SCHEMA, "unsupported schema version")
            allowed_events = {item.upper() for item in settings.tradingview_allowed_event_types}
            if allowed_events and parsed.event_type.value not in allowed_events:
                raise OperationsRejection(RejectionCode.INVALID_EVENT_TYPE, "event type is disabled")
            if parsed.event_type == OperationsEventType.HEARTBEAT:
                return self._heartbeat(parsed, received_at, request_id)
            result = await self._process_signal(parsed, received_at, request_id)
            audit_service.record("tradingview.webhook.accepted", request_id, signal_id=result.signal_id, trade_id=result.trade_id)
            return {
                "accepted": True,
                "status": result.status,
                "signal_id": result.signal_id,
                "trade_id": result.trade_id,
                "request_id": request_id,
                "delivery_status": result.delivery_status,
            }
        except OperationsRejection as exc:
            record = self._record_rejection(payload, exc, received_at, request_id)
            audit_service.record("tradingview.webhook.rejected", request_id, rejection_code=exc.code.value, result="rejected")
            return {
                "accepted": False,
                "request_id": request_id,
                "rejection_code": record.code,
                "retryable": record.retryable,
            }
        except (ValidationError, ValueError) as exc:
            rejection = OperationsRejection(RejectionCode.VALIDATION_ERROR, "invalid TradingView payload")
            record = self._record_rejection(payload, rejection, received_at, request_id)
            audit_service.record("tradingview.webhook.rejected", request_id, rejection_code=record.code, result="rejected", error_type=exc.__class__.__name__)
            return {
                "accepted": False,
                "request_id": request_id,
                "rejection_code": record.code,
                "retryable": False,
            }

    def _authenticate(self, payload: CanonicalWebhookPayload) -> None:
        if not settings.webhook_shared_secret:
            raise ConfigurationError("webhook shared secret is not configured")
        if not payload.secret or not hmac.compare_digest(payload.secret, settings.webhook_shared_secret):
            raise OperationsRejection(RejectionCode.INVALID_SECRET, "invalid webhook secret")

    async def _process_signal(self, payload: CanonicalWebhookPayload, received_at: str, request_id: str) -> OperationsResult:
        state = self.store.load_state()
        state.last_signal_received_at = received_at
        self.store.save_state(state)
        if state.intake_state == IntakeState.MAINTENANCE:
            raise OperationsRejection(RejectionCode.SYSTEM_MAINTENANCE, "operations are in maintenance")
        if state.intake_state == IntakeState.PAUSED and payload.event_type == OperationsEventType.SIGNAL_OPEN:
            raise OperationsRejection(RejectionCode.SIGNALS_PAUSED, "signal intake is paused")
        if not settings.signals_enabled and payload.event_type == OperationsEventType.SIGNAL_OPEN:
            raise OperationsRejection(RejectionCode.SIGNALS_PAUSED, "signals are disabled")
        if payload.event_type != OperationsEventType.SIGNAL_OPEN and not settings.trade_updates_enabled:
            raise OperationsRejection(RejectionCode.SYSTEM_MAINTENANCE, "trade updates are disabled")
        if self.store.signal_exists(payload.signal_id):
            raise OperationsRejection(RejectionCode.DUPLICATE_SIGNAL, "duplicate signal")
        if self.store.alert_exists(payload.alert_id):
            raise OperationsRejection(RejectionCode.DUPLICATE_ALERT, "duplicate alert")

        profile = self.symbols.normalize(payload.symbol)
        timeframe = self.timeframes.normalize(payload.timeframe)
        self._allowed(profile, timeframe)
        signal_age = self._signal_age(payload.signal_timestamp)
        warning_code = self._age_gate(signal_age)
        entry_deviation = self._entry_deviation(payload)
        if entry_deviation is not None and entry_deviation > self._deviation_limit(profile):
            raise OperationsRejection(RejectionCode.ENTRY_DEVIATION_TOO_HIGH, "entry deviation too high")
        self._quality_gate(payload, profile)

        trade_id = payload.trade_id or f"QAT-{payload.signal_id}"
        signal = self._to_queen_signal(payload, profile, timeframe, trade_id)
        replay_key = f"operations:{payload.signal_id}:{payload.alert_id}"
        action, stored_result = idempotency_store.begin_webhook(replay_key, signal.model_dump(mode="json"))
        if action == "completed" and stored_result:
            return OperationsResult(status="duplicate_completed", signal_id=payload.signal_id, trade_id=stored_result.get("trade_id"))
        if action in {"active", "permanent"}:
            raise OperationsRejection(RejectionCode.DUPLICATE_SIGNAL, "duplicate signal")

        trade = self.trade_engine.consume_signal(signal, request_id=request_id, correlation_id=payload.signal_id)
        record = self._signal_record(
            payload,
            profile,
            timeframe,
            received_at,
            signal_age,
            entry_deviation,
            SignalDecision.WARNING if warning_code else SignalDecision.ACCEPTED,
            trade.trade_id if trade else trade_id,
            warning_code=warning_code.value if warning_code else None,
        )
        self.store.append_signal(record)
        delivery_status = None
        if settings.telegram_enabled:
            message = self._message(signal, payload, profile, record)
            routed = self._routed(signal, payload, record.trading_style)
            delivery = await self.delivery.deliver(routed, message, request_id)
            delivery_status = delivery.status
            state = self.store.load_state()
            if delivery.delivered:
                state.last_telegram_success_at = now_iso()
            else:
                state.last_telegram_failure_at = now_iso()
            self.store.save_state(state)
        state = self.store.load_state()
        state.last_accepted_signal_at = received_at
        if payload.event_type != OperationsEventType.SIGNAL_OPEN:
            state.last_trade_update_at = received_at
        self.store.save_state(state)
        idempotency_store.mark_webhook(replay_key, WebhookOperationState.COMPLETED, result={"signal_id": payload.signal_id, "trade_id": record.trade_id})
        audit_service.record("signal.quality.accepted", request_id, signal_id=record.signal_id, trade_id=record.trade_id)
        return OperationsResult(status=record.decision.lower(), signal_id=record.signal_id, trade_id=record.trade_id, record=record, delivery_status=delivery_status)

    def _heartbeat(self, payload: CanonicalWebhookPayload, received_at: str, request_id: str) -> dict[str, Any]:
        state = self.store.load_state()
        state.last_tradingview_heartbeat_at = received_at
        self.store.save_state(state)
        self.store.append_heartbeat({"received_at": received_at, "alert_id": payload.alert_id, "signal_id": payload.signal_id, "metadata": payload.metadata})
        audit_service.record("tradingview.heartbeat.received", request_id, alert_id=payload.alert_id)
        return {"accepted": True, "status": "heartbeat", "signal_id": payload.signal_id, "trade_id": None, "request_id": request_id}

    def _allowed(self, profile: SymbolProfile, timeframe: str) -> None:
        allowed_symbols = {self.symbols.normalize(item).canonical for item in settings.tradingview_allowed_symbols}
        if allowed_symbols and profile.canonical not in allowed_symbols:
            raise OperationsRejection(RejectionCode.SYMBOL_DISABLED, "symbol is not allowed")
        allowed_timeframes = {self.timeframes.normalize(item) for item in settings.tradingview_allowed_timeframes}
        if allowed_timeframes and timeframe not in allowed_timeframes:
            raise OperationsRejection(RejectionCode.TIMEFRAME_DISABLED, "timeframe is not allowed")
        if not profile.enabled:
            raise OperationsRejection(RejectionCode.SYMBOL_DISABLED, "symbol is disabled")

    def _signal_age(self, timestamp: str | None) -> float | None:
        parsed = parse_iso(timestamp)
        if parsed is None:
            return None
        return (datetime.now(UTC) - parsed).total_seconds()

    def _age_gate(self, signal_age: float | None) -> RejectionCode | None:
        if signal_age is None:
            return None
        if signal_age < -settings.tradingview_future_tolerance_seconds:
            raise OperationsRejection(RejectionCode.FUTURE_SIGNAL, "future-dated signal")
        if signal_age > settings.tradingview_max_signal_age_seconds:
            if settings.signal_age_policy == "REJECT":
                raise OperationsRejection(RejectionCode.STALE_SIGNAL, "stale signal")
            return RejectionCode.STALE_SIGNAL
        if signal_age > settings.tradingview_warn_signal_age_seconds:
            return RejectionCode.STALE_SIGNAL
        return None

    def _entry_deviation(self, payload: CanonicalWebhookPayload) -> float | None:
        if payload.price_at_alert is None or payload.entry in {None, 0}:
            return None
        return abs(payload.price_at_alert - payload.entry) / abs(payload.entry) * 100

    def _deviation_limit(self, profile: SymbolProfile) -> float:
        if profile.asset_class == "GOLD":
            return settings.gold_entry_deviation_percent
        if profile.asset_class == "INDEX":
            return settings.nasdaq_entry_deviation_percent
        if profile.asset_class == "FOREX":
            return settings.forex_entry_deviation_percent
        if profile.asset_class == "CRYPTO":
            return settings.crypto_entry_deviation_percent
        return settings.default_entry_deviation_percent

    def _quality_gate(self, payload: CanonicalWebhookPayload, profile: SymbolProfile) -> None:
        if payload.confidence is not None and payload.confidence < settings.signal_min_confidence:
            raise OperationsRejection(RejectionCode.CONFIDENCE_BELOW_THRESHOLD, "confidence below threshold")
        if payload.event_type != OperationsEventType.SIGNAL_OPEN:
            return
        if payload.side == Side.BUY:
            if payload.stop_loss is None or payload.entry is None or payload.stop_loss >= payload.entry:
                raise OperationsRejection(RejectionCode.INVALID_PRICE_STRUCTURE, "BUY stop loss must be below entry")
            if any(tp.price <= payload.entry for tp in payload.take_profits):
                raise OperationsRejection(RejectionCode.INVALID_PRICE_STRUCTURE, "BUY take profits must be above entry")
        if payload.side == Side.SELL:
            if payload.stop_loss is None or payload.entry is None or payload.stop_loss <= payload.entry:
                raise OperationsRejection(RejectionCode.INVALID_PRICE_STRUCTURE, "SELL stop loss must be above entry")
            if any(tp.price >= payload.entry for tp in payload.take_profits):
                raise OperationsRejection(RejectionCode.INVALID_PRICE_STRUCTURE, "SELL take profits must be below entry")

    def _to_queen_signal(self, payload: CanonicalWebhookPayload, profile: SymbolProfile, timeframe: str, trade_id: str) -> QueenSignalPayload:
        event, actionability, action = self._event_mapping(payload)
        direction = Direction.BULLISH if payload.side == Side.BUY else Direction.BEARISH if payload.side == Side.SELL else Direction.NEUTRAL
        return QueenSignalPayload(
            schema_version=payload.schema_version,
            engine="Queen Engine",
            engine_version="2.0",
            signal_id=payload.signal_id,
            event_id=f"{payload.alert_id}:{payload.event_type.value}",
            setup_id=payload.setup_type,
            entry_id=payload.alert_id if payload.event_type == OperationsEventType.SIGNAL_OPEN else None,
            trade_id=trade_id,
            timestamp=int((parse_iso(payload.signal_timestamp) or datetime.now(UTC)).timestamp() * 1000),
            symbol=profile.canonical,
            exchange=payload.exchange,
            timeframe=timeframe,
            event=event,
            direction=direction,
            action=action,
            actionability=actionability,
            entry_price=payload.entry or payload.close_price,
            stop_price=payload.stop_loss,
            targets=[Target(name=f"TP{tp.level}", price=tp.price) for tp in payload.take_profits],
            session=payload.session,
            reason_codes=[payload.event_type.value],
            payload_signature_version="shared-secret-v1",
            message=payload.close_reason,
            raw_payload=payload.model_dump(mode="json", exclude={"secret"}),
        )

    def _event_mapping(self, payload: CanonicalWebhookPayload) -> tuple[SignalEvent, Actionability, SignalAction]:
        if payload.event_type == OperationsEventType.SIGNAL_OPEN:
            return SignalEvent.TRADE_OPENED_SIGNAL, Actionability.ACTIONABLE, SignalAction.LONG if payload.side == Side.BUY else SignalAction.SHORT
        if payload.event_type == OperationsEventType.TP_HIT:
            return SignalEvent.TARGET_REACHED_SIGNAL, Actionability.MANAGEMENT, SignalAction.TARGET_REACHED
        if payload.event_type == OperationsEventType.SL_HIT:
            return SignalEvent.TRADE_STOPPED_SIGNAL, Actionability.TERMINAL, SignalAction.CLOSE_TRADE
        if payload.event_type == OperationsEventType.TRADE_CANCELLED:
            return SignalEvent.TRADE_INVALIDATED_SIGNAL, Actionability.TERMINAL, SignalAction.CANCEL_TRADE
        if payload.event_type == OperationsEventType.TRADE_EXPIRED:
            return SignalEvent.TRADE_EXPIRED_SIGNAL, Actionability.TERMINAL, SignalAction.CLOSE_TRADE
        if payload.event_type == OperationsEventType.TRADE_CLOSED:
            return SignalEvent.TRADE_CLOSED_SIGNAL, Actionability.TERMINAL, SignalAction.CLOSE_TRADE
        return SignalEvent.ENTRY_EXECUTED_SIGNAL, Actionability.MANAGEMENT, SignalAction.NONE

    def _signal_record(
        self,
        payload: CanonicalWebhookPayload,
        profile: SymbolProfile,
        timeframe: str,
        received_at: str,
        signal_age: float | None,
        entry_deviation: float | None,
        decision: SignalDecision,
        trade_id: str | None,
        *,
        warning_code: str | None = None,
    ) -> SignalRecord:
        return SignalRecord(
            signal_id=payload.signal_id,
            alert_id=payload.alert_id,
            schema_version=payload.schema_version,
            source=payload.source,
            event_type=payload.event_type.value,
            symbol=profile.canonical,
            original_symbol=payload.symbol,
            timeframe=timeframe,
            side=payload.side.value if payload.side else None,
            entry=payload.entry,
            stop_loss=payload.stop_loss,
            take_profits=[tp.model_dump(mode="json") for tp in payload.take_profits],
            confidence=payload.confidence,
            session=payload.session,
            setup_type=payload.setup_type,
            trading_style=self.timeframes.trading_style(timeframe, payload.trading_style, profile),
            signal_timestamp=payload.signal_timestamp,
            received_at=received_at,
            signal_age_seconds=round(signal_age, 3) if signal_age is not None else None,
            price_at_alert=payload.price_at_alert,
            entry_deviation_percent=round(entry_deviation, 6) if entry_deviation is not None else None,
            decision=decision.value,
            warning_code=warning_code,
            trade_id=trade_id,
            mode=payload.mode or settings.paper_signal_mode,
            metadata=redact(payload.metadata),
        )

    def _routed(self, signal: QueenSignalPayload, payload: CanonicalWebhookPayload, trading_style: str | None) -> RoutedEvent:
        destination = self._destination(trading_style)
        return RoutedEvent(payload=signal, route=(trading_style or "default").lower(), destinations=[destination] if destination else [], priority=90, correlation_id=payload.signal_id)

    def _destination(self, trading_style: str | None) -> str:
        default = settings.telegram_default_chat_id or (settings.telegram_chat_ids[0] if settings.telegram_chat_ids else "")
        if trading_style == "SCALP" and settings.telegram_scalp_chat_id:
            return settings.telegram_scalp_chat_id
        if trading_style == "INTRADAY" and settings.telegram_intraday_chat_id:
            return settings.telegram_intraday_chat_id
        if trading_style == "SWING" and settings.telegram_swing_chat_id:
            return settings.telegram_swing_chat_id
        return default

    def _message(self, signal: QueenSignalPayload, payload: CanonicalWebhookPayload, profile: SymbolProfile, record: SignalRecord) -> MessageEnvelope:
        precision = profile.decimal_precision
        def money(value: float | None) -> str:
            return "-" if value is None else f"{value:.{precision}f}"
        if payload.event_type == OperationsEventType.SIGNAL_OPEN:
            tp_lines = [f"TP{tp.level}: {money(tp.price)}" for tp in payload.take_profits]
            warning = f"\nDelayed signal warning: {record.warning_code}" if record.warning_code else ""
            body = "\n".join(
                [
                    "QUEEN AI TRADER",
                    "",
                    f"{payload.side.value if payload.side else '-'} - {profile.display_name}",
                    f"Symbol: {profile.canonical}",
                    f"Timeframe: {record.timeframe}m" if str(record.timeframe).isdigit() else f"Timeframe: {record.timeframe}",
                    f"Session: {payload.session or '-'}",
                    "",
                    f"Entry: {money(payload.entry)}",
                    f"Stop Loss: {money(payload.stop_loss)}",
                    "",
                    *tp_lines,
                    "",
                    f"Confidence: {payload.confidence if payload.confidence is not None else '-'}%",
                    f"Model: {payload.setup_type or '-'}",
                    f"Mode: {record.mode}",
                    f"Trade ID: {record.trade_id}",
                    f"Signal Time: {payload.signal_timestamp}",
                    f"Received: {record.received_at}",
                    warning,
                    "",
                    "Notification only. No broker execution is performed.",
                ]
            )
        else:
            price = payload.close_price or payload.price_at_alert or payload.entry
            body = "\n".join(
                [
                    f"{profile.display_name} UPDATE",
                    "",
                    payload.event_type.value.replace("_", " "),
                    f"Price: {money(price)}",
                    f"Trade: {signal.trade_id or '-'}",
                    "",
                    "Notification only. No broker execution is performed.",
                ]
            )
        return MessageEnvelope(payload=signal, route=record.trading_style or "default", format="telegram_markdown", body=body)

    def _record_rejection(self, payload: dict[str, Any], exc: OperationsRejection, received_at: str, request_id: str) -> RejectionRecord:
        record = RejectionRecord(
            signal_id=str(payload.get("signal_id") or "") or None,
            alert_id=str(payload.get("alert_id") or "") or None,
            event_type=str(payload.get("event_type") or "") or None,
            code=exc.code.value,
            message=exc.message,
            received_at=received_at,
            retryable=exc.retryable,
            metadata=redact({"request_id": request_id, "symbol": payload.get("symbol"), "timeframe": payload.get("timeframe")}),
        )
        self.store.append_rejection(record)
        state = self.store.load_state()
        state.last_rejected_signal_at = received_at
        state.recent_error = exc.code.value
        self.store.save_state(state)
        audit_service.record("signal.quality.rejected", request_id, signal_id=record.signal_id, rejection_code=record.code, result="rejected")
        return record

    def pause(self, actor: str | None = None) -> OperationsState:
        if not self.limiter.allow(f"operations-action:{actor or 'owner'}", settings.operations_action_rate_limit_per_minute):
            raise OperationsRejection(RejectionCode.RATE_LIMITED, "operations action rate limit exceeded", retryable=True)
        state = self.store.load_state()
        state.intake_state = IntakeState.PAUSED
        saved = self.store.save_state(state)
        audit_service.record("operations.paused", "", actor=actor)
        return saved

    def resume(self, actor: str | None = None) -> OperationsState:
        if not self.limiter.allow(f"operations-action:{actor or 'owner'}", settings.operations_action_rate_limit_per_minute):
            raise OperationsRejection(RejectionCode.RATE_LIMITED, "operations action rate limit exceeded", retryable=True)
        state = self.store.load_state()
        state.intake_state = IntakeState.RUNNING
        saved = self.store.save_state(state)
        audit_service.record("operations.resumed", "", actor=actor)
        return saved

    async def test_telegram(self, request_id: str, actor: str | None = None) -> dict[str, Any]:
        if not self.limiter.allow(f"telegram-test:{actor or 'owner'}", settings.telegram_test_rate_limit_per_minute):
            raise OperationsRejection(RejectionCode.RATE_LIMITED, "telegram test rate limit exceeded", retryable=True)
        payload = QueenSignalPayload(
            schema_version="1.0",
            engine="Queen Engine",
            engine_version="2.0",
            signal_id=f"telegram-test-{uuid.uuid4().hex}",
            event_id=f"telegram-test-{uuid.uuid4().hex}",
            trade_id=None,
            timestamp=int(time.time() * 1000),
            symbol="SYSTEM",
            timeframe="NA",
            event=SignalEvent.INFORMATIONAL_SIGNAL,
            direction=Direction.NEUTRAL,
            action=SignalAction.NONE,
            actionability=Actionability.INFORMATIONAL,
            payload_signature_version="shared-secret-v1",
        )
        routed = RoutedEvent(payload=payload, route="operations_test", destinations=[self._destination(None)] if self._destination(None) else [], priority=10, correlation_id=payload.signal_id)
        message = MessageEnvelope(payload=payload, route="operations_test", format="telegram_markdown", body="Queen AI Trader\nTelegram connection test succeeded.")
        audit_service.record("telegram.test.requested", request_id, actor=actor)
        delivery = await self.delivery.deliver(routed, message, request_id)
        audit_service.record("telegram.test.delivered" if delivery.delivered else "telegram.test.failed", request_id, actor=actor, status=delivery.status)
        return {"delivered": delivery.delivered, "status": delivery.status, "attempts": [attempt.model_dump(mode="json") for attempt in delivery.attempts]}

    def status(self) -> dict[str, Any]:
        state = self.store.load_state()
        signals = self.store.list_signals(limit=settings.operations_history_limit)
        rejections = self.store.list_rejections(limit=settings.operations_history_limit)
        open_trades = trade_registry.find_open_trades()
        closed_trades = trade_registry.find_closed_trades()
        return {
            "mode": state.mode,
            "system_status": "ONLINE" if state.intake_state == IntakeState.RUNNING else state.intake_state.value,
            "signals_enabled": settings.signals_enabled and state.intake_state == IntakeState.RUNNING,
            "tradingview": {
                "status": self._connection_status(state.last_tradingview_heartbeat_at or state.last_signal_received_at).value,
                "last_heartbeat_at": state.last_tradingview_heartbeat_at,
                "last_signal_at": state.last_signal_received_at,
                "seconds_since_last_event": self._seconds_since(state.last_tradingview_heartbeat_at or state.last_signal_received_at),
            },
            "telegram": {
                "status": self._telegram_status(state).value,
                "last_success_at": state.last_telegram_success_at,
                "last_failure_at": state.last_telegram_failure_at,
            },
            "today": {
                "signals_received": len(signals),
                "signals_accepted": len([item for item in signals if item.decision in {SignalDecision.ACCEPTED.value, SignalDecision.WARNING.value}]),
                "signals_rejected": len(rejections),
                "open_trades": len(open_trades),
                "closed_trades": len(closed_trades),
                "tp_hits": sum(1 for trade in closed_trades + open_trades for item in trade.state_history if item.new_state in {TradeLifecycleState.TARGET_1, TradeLifecycleState.TARGET_2, TradeLifecycleState.TARGET_3}),
                "sl_hits": sum(1 for trade in closed_trades + open_trades if trade.current_state == TradeLifecycleState.STOPPED or trade.final_disposition == TradeLifecycleState.STOPPED),
            },
            "recent_error": state.recent_error,
        }

    def connectivity(self) -> dict[str, Any]:
        status = self.status()
        return {"tradingview": status["tradingview"], "telegram": status["telegram"], "signal_engine": {"status": "PAUSED" if self.store.load_state().intake_state == IntakeState.PAUSED else "ACTIVE"}}

    def configuration(self) -> dict[str, Any]:
        return {
            "personal_operations_mode": settings.personal_operations_mode,
            "mode": self.store.load_state().mode,
            "signals_enabled": settings.signals_enabled,
            "trade_updates_enabled": settings.trade_updates_enabled,
            "allowed_symbols": list(settings.tradingview_allowed_symbols),
            "allowed_timeframes": list(settings.tradingview_allowed_timeframes),
            "allowed_event_types": list(settings.tradingview_allowed_event_types),
            "telegram_enabled": settings.telegram_enabled,
            "paper_signal_mode": settings.paper_signal_mode,
            "history_limit": settings.operations_history_limit,
            "secrets": "[redacted]",
        }

    def _connection_status(self, timestamp: str | None) -> ConnectionStatus:
        seconds = self._seconds_since(timestamp)
        if seconds is None:
            return ConnectionStatus.NEVER_CONNECTED
        return ConnectionStatus.STALE if seconds > settings.stale_connection_seconds else ConnectionStatus.CONNECTED

    def _telegram_status(self, state: OperationsState) -> TelegramStatus:
        if not settings.telegram_enabled:
            return TelegramStatus.DISABLED
        if state.last_telegram_success_at:
            return TelegramStatus.CONNECTED
        if state.last_telegram_failure_at:
            return TelegramStatus.FAILED
        return TelegramStatus.DEGRADED

    def _seconds_since(self, timestamp: str | None) -> int | None:
        parsed = parse_iso(timestamp)
        if not parsed:
            return None
        return max(0, int((datetime.now(UTC) - parsed).total_seconds()))


operations_store = OperationsStore()
operations_service = PersonalOperationsService(operations_store)
