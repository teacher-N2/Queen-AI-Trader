from .analytics_engine import AnalyticsEngine, analytics_engine
from .analytics_models import (
    AnalyticsFilter,
    EventStatistics,
    GroupStatistics,
    LifecycleStatistics,
    OverallStatistics,
    RiskStatistics,
)


class AnalyticsQueryService:
    def __init__(self, engine: AnalyticsEngine = analytics_engine):
        self.engine = engine

    def getOverallStatistics(self, filters: AnalyticsFilter | None = None) -> OverallStatistics:
        return self.engine.generate_report(filters).overall

    def getSessionStatistics(self, session: str | None = None) -> list[GroupStatistics]:
        report = self.engine.generate_report(AnalyticsFilter(session=session) if session else None)
        return report.sessions

    def getSymbolStatistics(self, symbol: str | None = None) -> list[GroupStatistics]:
        report = self.engine.generate_report(AnalyticsFilter(symbol=symbol) if symbol else None)
        return report.symbols

    def getTimeframeStatistics(self, timeframe: str | None = None) -> list[GroupStatistics]:
        report = self.engine.generate_report(AnalyticsFilter(timeframe=timeframe) if timeframe else None)
        return report.timeframes

    def getTradeStatistics(self, filters: AnalyticsFilter | None = None) -> RiskStatistics:
        return self.engine.generate_report(filters).risk

    def getLifecycleStatistics(self, filters: AnalyticsFilter | None = None) -> LifecycleStatistics:
        return self.engine.generate_report(filters).lifecycle

    def getEventStatistics(self, filters: AnalyticsFilter | None = None) -> EventStatistics:
        return self.engine.generate_report(filters).events


analytics_queries = AnalyticsQueryService()
