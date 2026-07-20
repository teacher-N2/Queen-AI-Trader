from collections import Counter
from datetime import datetime
from statistics import mean
from typing import Any, Callable

from .analytics_models import (
    CounterMetric,
    EventStatistics,
    LifecycleStatistics,
    OverallStatistics,
    QualityStatistics,
    RiskStatistics,
    SetupStatistics,
)
from .trade_state import Trade, TradeLifecycleState, TradeTransitionRecord


WIN_STATES = {TradeLifecycleState.TARGET_3}
LOSS_STATES = {TradeLifecycleState.STOPPED}
BREAK_EVEN_STATES = {TradeLifecycleState.BREAK_EVEN}
OPEN_STATES = {
    TradeLifecycleState.CREATED,
    TradeLifecycleState.QUALIFIED,
    TradeLifecycleState.ENTRY_READY,
    TradeLifecycleState.ENTRY_EXECUTED,
    TradeLifecycleState.OPEN,
    TradeLifecycleState.PARTIAL_EXIT,
    TradeLifecycleState.BREAK_EVEN,
    TradeLifecycleState.STOP_UPDATED,
    TradeLifecycleState.TARGET_1,
    TradeLifecycleState.TARGET_2,
}
CLOSED_STATES = {
    TradeLifecycleState.TARGET_3,
    TradeLifecycleState.STOPPED,
    TradeLifecycleState.INVALIDATED,
    TradeLifecycleState.EXPIRED,
    TradeLifecycleState.CLOSED,
}


def parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def seconds_between(start: str | None, end: str | None) -> float | None:
    start_dt = parse_dt(start)
    end_dt = parse_dt(end)
    if not start_dt or not end_dt:
        return None
    return max((end_dt - start_dt).total_seconds(), 0.0)


def safe_rate(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round((numerator / denominator) * 100, 2)


def non_null_mean(values: list[float | None]) -> float | None:
    clean_values = [value for value in values if value is not None]
    if not clean_values:
        return None
    return round(mean(clean_values), 4)


def classify_trade(trade: Trade) -> str:
    states = [record.new_state for record in trade.state_history]
    if TradeLifecycleState.TARGET_3 in states or trade.final_disposition == TradeLifecycleState.TARGET_3:
        return "win"
    if TradeLifecycleState.STOPPED in states or trade.final_disposition == TradeLifecycleState.STOPPED:
        return "loss"
    if TradeLifecycleState.BREAK_EVEN in states and trade.current_state in {TradeLifecycleState.CLOSED, TradeLifecycleState.STOPPED}:
        return "break_even"
    return "open" if trade.current_state in OPEN_STATES else "closed"


def transition_time(trade: Trade, state: TradeLifecycleState) -> str | None:
    for record in trade.state_history:
        if record.new_state == state:
            return record.timestamp
    return None


def first_target_time(trade: Trade) -> str | None:
    for state in (TradeLifecycleState.TARGET_1, TradeLifecycleState.TARGET_2, TradeLifecycleState.TARGET_3):
        found = transition_time(trade, state)
        if found:
            return found
    return None


def planned_rr(trade: Trade) -> float | None:
    if trade.entry_price is None or trade.stop_price is None or not trade.targets:
        return None
    risk = abs(trade.entry_price - trade.stop_price)
    if risk <= 0:
        return None
    best_target = max(abs(target.price - trade.entry_price) for target in trade.targets)
    return round(best_target / risk, 4)


def realized_rr(trade: Trade) -> float | None:
    planned = planned_rr(trade)
    if planned is None:
        return None
    outcome = classify_trade(trade)
    if outcome == "win":
        return planned
    if outcome == "loss":
        return -1.0
    if outcome == "break_even":
        return 0.0
    if TradeLifecycleState.TARGET_2 in [record.new_state for record in trade.state_history]:
        return round(planned * 0.66, 4)
    if TradeLifecycleState.TARGET_1 in [record.new_state for record in trade.state_history]:
        return round(planned * 0.33, 4)
    return None


class AnalyticsMetrics:
    def overall(self, trades: list[Trade]) -> OverallStatistics:
        total = len(trades)
        outcomes = Counter(classify_trade(trade) for trade in trades)
        closed = sum(1 for trade in trades if classify_trade(trade) != "open")
        return OverallStatistics(
            total_trades=total,
            open_trades=outcomes["open"],
            closed_trades=closed,
            winning_trades=outcomes["win"],
            losing_trades=outcomes["loss"],
            break_even_trades=outcomes["break_even"],
            win_rate=safe_rate(outcomes["win"], closed),
            loss_rate=safe_rate(outcomes["loss"], closed),
            break_even_rate=safe_rate(outcomes["break_even"], closed),
            average_trade_duration_seconds=non_null_mean([seconds_between(trade.created_at, trade.updated_at) for trade in trades]),
            average_time_to_entry_seconds=non_null_mean([self._time_to_entry(trade) for trade in trades]),
            average_time_to_tp_seconds=non_null_mean([self._time_to_tp(trade) for trade in trades]),
            average_time_to_sl_seconds=non_null_mean([self._time_to_sl(trade) for trade in trades]),
        )

    def risk(self, trades: list[Trade]) -> RiskStatistics:
        planned = [planned_rr(trade) for trade in trades]
        realized = [realized_rr(trade) for trade in trades]
        clean_realized = [value for value in realized if value is not None]
        losses = abs(sum(value for value in clean_realized if value < 0))
        wins = sum(value for value in clean_realized if value > 0)
        return RiskStatistics(
            average_rr=non_null_mean(planned),
            average_realized_rr=non_null_mean(realized),
            best_rr=max(clean_realized) if clean_realized else None,
            worst_rr=min(clean_realized) if clean_realized else None,
            maximum_consecutive_wins=self._max_streak(trades, "win"),
            maximum_consecutive_losses=self._max_streak(trades, "loss"),
            recovery_ratio=round(wins / losses, 4) if losses else None,
        )

    def lifecycle(self, trades: list[Trade]) -> LifecycleStatistics:
        return LifecycleStatistics(
            average_signal_to_entry_seconds=non_null_mean([self._time_to_entry(trade) for trade in trades]),
            average_entry_to_tp_seconds=non_null_mean([self._entry_to_tp(trade) for trade in trades]),
            average_entry_to_sl_seconds=non_null_mean([self._entry_to_sl(trade) for trade in trades]),
            average_break_even_duration_seconds=non_null_mean([self._break_even_duration(trade) for trade in trades]),
            average_lifecycle_duration_seconds=non_null_mean([seconds_between(trade.created_at, trade.updated_at) for trade in trades]),
        )

    def events(self, trades: list[Trade], audit_records: list[dict[str, Any]]) -> EventStatistics:
        event_counter: Counter[str] = Counter()
        transition_counter: Counter[str] = Counter()
        transition_total = 0
        for trade in trades:
            transition_total += len(trade.state_history)
            for record in trade.state_history:
                event_counter[record.source_event] += 1
                previous = record.previous_state.value if record.previous_state else "NONE"
                transition_counter[f"{previous}->{record.new_state.value}"] += 1
        duplicate_events = sum(1 for record in audit_records if str(record.get("event", "")).lower().find("duplicate") >= 0)
        invalid_transitions = sum(1 for record in audit_records if record.get("event") == "trade_state_error")
        denominator = max(sum(event_counter.values()), 1)
        return EventStatistics(
            most_common_events=self._top(event_counter),
            most_common_transitions=self._top(transition_counter),
            average_transitions_per_trade=round(transition_total / len(trades), 4) if trades else 0.0,
            duplicate_event_rate=safe_rate(duplicate_events, denominator),
            invalid_transition_attempts=invalid_transitions,
        )

    def quality(self, trades: list[Trade], audit_records: list[dict[str, Any]], delivery_records: list[dict[str, Any]]) -> QualityStatistics:
        delivered = sum(1 for record in delivery_records if record.get("status") == "delivered")
        delivery_total = len(delivery_records)
        validation_failures = sum(1 for record in audit_records if record.get("event") == "validation_failed")
        authentication_failures = sum(1 for record in audit_records if record.get("event") == "authentication_failed")
        replay_events = sum(1 for record in audit_records if "replay" in str(record.get("event", "")).lower())
        webhook_events = sum(1 for record in audit_records if record.get("event") == "webhook_received")
        actionable = sum(1 for trade in trades if trade.entry_price is not None and trade.stop_price is not None)
        executed = sum(1 for trade in trades if transition_time(trade, TradeLifecycleState.ENTRY_EXECUTED))
        return QualityStatistics(
            signal_quality=safe_rate(actionable, len(trades)) if trades else None,
            execution_quality=safe_rate(executed, actionable) if actionable else None,
            delivery_success_rate=safe_rate(delivered, delivery_total),
            replay_detection_rate=safe_rate(replay_events, webhook_events),
            validation_failure_rate=safe_rate(validation_failures, webhook_events),
            authentication_failure_rate=safe_rate(authentication_failures, webhook_events),
        )

    def setup(self, trades: list[Trade]) -> SetupStatistics:
        return SetupStatistics(
            best_setup=self._best_group(trades, lambda trade: trade.setup_id),
            worst_setup=self._worst_group(trades, lambda trade: trade.setup_id),
            best_entry_type=self._best_metadata(trades, "entry_type"),
            best_confirmation=self._best_metadata(trades, "confirmation"),
            best_order_block=self._best_metadata(trades, "order_block"),
            best_fvg=self._best_metadata(trades, "fvg"),
            best_confluence=self._best_metadata(trades, "confluence"),
        )

    def _time_to_entry(self, trade: Trade) -> float | None:
        return seconds_between(trade.created_at, transition_time(trade, TradeLifecycleState.ENTRY_EXECUTED))

    def _time_to_tp(self, trade: Trade) -> float | None:
        return seconds_between(trade.created_at, first_target_time(trade))

    def _time_to_sl(self, trade: Trade) -> float | None:
        return seconds_between(trade.created_at, transition_time(trade, TradeLifecycleState.STOPPED))

    def _entry_to_tp(self, trade: Trade) -> float | None:
        return seconds_between(transition_time(trade, TradeLifecycleState.ENTRY_EXECUTED), first_target_time(trade))

    def _entry_to_sl(self, trade: Trade) -> float | None:
        return seconds_between(transition_time(trade, TradeLifecycleState.ENTRY_EXECUTED), transition_time(trade, TradeLifecycleState.STOPPED))

    def _break_even_duration(self, trade: Trade) -> float | None:
        break_even_at = transition_time(trade, TradeLifecycleState.BREAK_EVEN)
        if not break_even_at:
            return None
        later_times = [record.timestamp for record in trade.state_history if parse_dt(record.timestamp) and parse_dt(record.timestamp) > parse_dt(break_even_at)]
        return seconds_between(break_even_at, later_times[0]) if later_times else None

    def _max_streak(self, trades: list[Trade], outcome: str) -> int:
        sorted_trades = sorted(trades, key=lambda trade: parse_dt(trade.updated_at) or datetime.min)
        best = 0
        current = 0
        for trade in sorted_trades:
            if classify_trade(trade) == outcome:
                current += 1
                best = max(best, current)
            elif classify_trade(trade) in {"win", "loss"}:
                current = 0
        return best

    def _top(self, counter: Counter[str], limit: int = 10) -> list[CounterMetric]:
        return [CounterMetric(name=name, count=count) for name, count in counter.most_common(limit)]

    def _best_group(self, trades: list[Trade], key_fn: Callable[[Trade], str | None]) -> str | None:
        return self._group_by_score(trades, key_fn, reverse=True)

    def _worst_group(self, trades: list[Trade], key_fn: Callable[[Trade], str | None]) -> str | None:
        return self._group_by_score(trades, key_fn, reverse=False)

    def _group_by_score(self, trades: list[Trade], key_fn: Callable[[Trade], str | None], *, reverse: bool) -> str | None:
        groups: dict[str, list[float]] = {}
        for trade in trades:
            key = key_fn(trade)
            score = realized_rr(trade)
            if key and score is not None:
                groups.setdefault(key, []).append(score)
        if not groups:
            return None
        ranked = sorted(groups.items(), key=lambda item: mean(item[1]), reverse=reverse)
        return ranked[0][0]

    def _best_metadata(self, trades: list[Trade], key: str) -> str | None:
        return self._best_group(trades, lambda trade: str(trade.metadata.get(key)) if trade.metadata.get(key) else None)


analytics_metrics = AnalyticsMetrics()
