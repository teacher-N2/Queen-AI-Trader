from .analytics_metrics import AnalyticsMetrics, analytics_metrics
from .analytics_models import AnalyticsFilter, AnalyticsReport, GroupStatistics
from .analytics_registry import AnalyticsRegistry
from .trade_state import Trade


class AnalyticsReportBuilder:
    def __init__(self, metrics: AnalyticsMetrics = analytics_metrics):
        self.metrics = metrics

    def build(
        self,
        trades: list[Trade],
        *,
        audit_records: list[dict],
        delivery_records: list[dict],
        filters: AnalyticsFilter | None = None,
    ) -> AnalyticsReport:
        active_filters = filters or AnalyticsFilter()
        registry = AnalyticsRegistry(trades)
        filtered_trades = registry.filtered(active_filters)
        filtered_registry = AnalyticsRegistry(filtered_trades)
        return AnalyticsReport(
            filters=active_filters,
            overall=self.metrics.overall(filtered_trades),
            risk=self.metrics.risk(filtered_trades),
            lifecycle=self.metrics.lifecycle(filtered_trades),
            events=self.metrics.events(filtered_trades, audit_records),
            quality=self.metrics.quality(filtered_trades, audit_records, delivery_records),
            sessions=self._groups(filtered_registry.by_session),
            symbols=self._groups(filtered_registry.by_symbol),
            timeframes=self._groups(filtered_registry.by_timeframe),
            setup=self.metrics.setup(filtered_trades),
            metadata={
                "source": "backend_trade_history",
                "read_only": True,
                "trade_count": len(filtered_trades),
            },
        )

    def _groups(self, grouped_trades: dict[str, list[Trade]]) -> list[GroupStatistics]:
        return [
            GroupStatistics(
                group=group,
                overall=self.metrics.overall(trades),
                risk=self.metrics.risk(trades),
            )
            for group, trades in sorted(grouped_trades.items(), key=lambda item: item[0])
        ]


analytics_report_builder = AnalyticsReportBuilder()
