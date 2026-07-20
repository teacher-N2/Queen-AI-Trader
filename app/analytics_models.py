from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class AnalyticsFilter(BaseModel):
    symbol: str | None = None
    session: str | None = None
    timeframe: str | None = None
    setup_id: str | None = None


class CounterMetric(BaseModel):
    name: str
    count: int


class OverallStatistics(BaseModel):
    total_trades: int = 0
    open_trades: int = 0
    closed_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    break_even_trades: int = 0
    win_rate: float = 0.0
    loss_rate: float = 0.0
    break_even_rate: float = 0.0
    average_trade_duration_seconds: float | None = None
    average_time_to_entry_seconds: float | None = None
    average_time_to_tp_seconds: float | None = None
    average_time_to_sl_seconds: float | None = None


class RiskStatistics(BaseModel):
    average_rr: float | None = None
    average_realized_rr: float | None = None
    best_rr: float | None = None
    worst_rr: float | None = None
    maximum_consecutive_wins: int = 0
    maximum_consecutive_losses: int = 0
    recovery_ratio: float | None = None


class LifecycleStatistics(BaseModel):
    average_signal_to_entry_seconds: float | None = None
    average_entry_to_tp_seconds: float | None = None
    average_entry_to_sl_seconds: float | None = None
    average_break_even_duration_seconds: float | None = None
    average_lifecycle_duration_seconds: float | None = None


class EventStatistics(BaseModel):
    most_common_events: list[CounterMetric] = Field(default_factory=list)
    most_common_transitions: list[CounterMetric] = Field(default_factory=list)
    average_transitions_per_trade: float = 0.0
    duplicate_event_rate: float = 0.0
    invalid_transition_attempts: int = 0


class QualityStatistics(BaseModel):
    signal_quality: float | None = None
    execution_quality: float | None = None
    delivery_success_rate: float = 0.0
    replay_detection_rate: float = 0.0
    validation_failure_rate: float = 0.0
    authentication_failure_rate: float = 0.0


class GroupStatistics(BaseModel):
    group: str
    overall: OverallStatistics
    risk: RiskStatistics


class SetupStatistics(BaseModel):
    best_setup: str | None = None
    worst_setup: str | None = None
    best_entry_type: str | None = None
    best_confirmation: str | None = None
    best_order_block: str | None = None
    best_fvg: str | None = None
    best_confluence: str | None = None


class AnalyticsReport(BaseModel):
    generated_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    filters: AnalyticsFilter = Field(default_factory=AnalyticsFilter)
    overall: OverallStatistics
    risk: RiskStatistics
    lifecycle: LifecycleStatistics
    events: EventStatistics
    quality: QualityStatistics
    sessions: list[GroupStatistics] = Field(default_factory=list)
    symbols: list[GroupStatistics] = Field(default_factory=list)
    timeframes: list[GroupStatistics] = Field(default_factory=list)
    setup: SetupStatistics = Field(default_factory=SetupStatistics)
    export_format: Literal["json", "csv"] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
