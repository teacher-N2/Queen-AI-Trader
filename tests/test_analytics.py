import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.analytics_engine import AnalyticsEngine
from app.analytics_export import AnalyticsExportService
from app.analytics_metrics import AnalyticsMetrics
from app.analytics_models import AnalyticsFilter
from app.analytics_reports import AnalyticsReportBuilder
from app.analytics_storage import AnalyticsStorage
from app.models import Direction, Target
from app.trade_history import TradeHistoryStore
from app.trade_state import Trade, TradeLifecycleState, TradeTransitionRecord


def transition(previous, new, at, event_id):
    return TradeTransitionRecord(
        timestamp=at.isoformat(),
        previous_state=previous,
        new_state=new,
        reason=new.value,
        source_event=f"{new.value}_SIGNAL",
        source_event_id=event_id,
    )


def trade(trade_id, outcome, symbol="XAUUSD", session="London", timeframe="M5"):
    base = datetime(2026, 7, 20, 8, 0, tzinfo=UTC)
    history = [
        transition(None, TradeLifecycleState.CREATED, base, f"{trade_id}-1"),
        transition(TradeLifecycleState.CREATED, TradeLifecycleState.ENTRY_EXECUTED, base + timedelta(minutes=5), f"{trade_id}-2"),
        transition(TradeLifecycleState.ENTRY_EXECUTED, TradeLifecycleState.OPEN, base + timedelta(minutes=6), f"{trade_id}-3"),
    ]
    final_state = TradeLifecycleState.OPEN
    final_disposition = None
    if outcome == "win":
        history.append(transition(TradeLifecycleState.OPEN, TradeLifecycleState.TARGET_3, base + timedelta(minutes=30), f"{trade_id}-4"))
        history.append(transition(TradeLifecycleState.TARGET_3, TradeLifecycleState.CLOSED, base + timedelta(minutes=31), f"{trade_id}-5"))
        final_state = TradeLifecycleState.CLOSED
        final_disposition = TradeLifecycleState.TARGET_3
    elif outcome == "loss":
        history.append(transition(TradeLifecycleState.OPEN, TradeLifecycleState.STOPPED, base + timedelta(minutes=20), f"{trade_id}-4"))
        history.append(transition(TradeLifecycleState.STOPPED, TradeLifecycleState.CLOSED, base + timedelta(minutes=21), f"{trade_id}-5"))
        final_state = TradeLifecycleState.CLOSED
        final_disposition = TradeLifecycleState.STOPPED
    return Trade(
        trade_id=trade_id,
        signal_id=f"sig-{trade_id}",
        setup_id="setup-a" if outcome == "win" else "setup-b",
        entry_id=f"entry-{trade_id}",
        symbol=symbol,
        timeframe=timeframe,
        direction=Direction.BULLISH,
        entry_price=100.0,
        stop_price=90.0,
        targets=[Target(name="TP3", price=130.0)],
        remaining_position=0.0,
        session=session,
        created_at=base.isoformat(),
        updated_at=(base + timedelta(minutes=31)).isoformat(),
        current_state=final_state,
        state_history=history,
        transition_count=len(history),
        final_disposition=final_disposition,
    )


class AnalyticsTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.path = Path(self.tmpdir.name)
        self.history = TradeHistoryStore(self.path)
        self.trades = [trade("t1", "win"), trade("t2", "loss", session="New York", timeframe="M15")]
        for item in self.trades:
            self.history.save_trade(item)
        self.storage = AnalyticsStorage(self.path, self.history)
        self.engine = AnalyticsEngine(self.storage, AnalyticsReportBuilder(AnalyticsMetrics()))

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_overall_statistics(self):
        report = self.engine.generate_report(use_cache=False)
        self.assertEqual(report.overall.total_trades, 2)
        self.assertEqual(report.overall.winning_trades, 1)
        self.assertEqual(report.overall.losing_trades, 1)
        self.assertEqual(report.overall.win_rate, 50.0)

    def test_filtering_by_session(self):
        report = self.engine.generate_report(AnalyticsFilter(session="London"), use_cache=False)
        self.assertEqual(report.overall.total_trades, 1)
        self.assertEqual(report.sessions[0].group, "London")

    def test_export_json_and_csv(self):
        report = self.engine.generate_report(use_cache=False)
        exporter = AnalyticsExportService(self.storage)
        json_text = exporter.to_json(report)
        csv_text = exporter.to_csv(report)
        self.assertIn('"total_trades": 2', json_text)
        self.assertIn("overall,all,total_trades,2", csv_text)

    def test_cache_reuse(self):
        report = self.engine.generate_report()
        cached = self.engine.generate_report()
        self.assertEqual(report.overall.total_trades, cached.overall.total_trades)


if __name__ == "__main__":
    unittest.main()
