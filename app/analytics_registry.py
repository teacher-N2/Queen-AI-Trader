from collections import defaultdict
from typing import Callable

from .analytics_models import AnalyticsFilter
from .trade_state import Trade


class AnalyticsRegistry:
    def __init__(self, trades: list[Trade]):
        self.trades = trades
        self.by_session = self._index(lambda trade: trade.session or "Unknown")
        self.by_symbol = self._index(lambda trade: trade.symbol or "Unknown")
        self.by_timeframe = self._index(lambda trade: trade.timeframe or "Unknown")
        self.by_setup = self._index(lambda trade: trade.setup_id or "Unknown")

    def filtered(self, filters: AnalyticsFilter | None = None) -> list[Trade]:
        if not filters:
            return list(self.trades)
        filtered = self.trades
        if filters.symbol:
            filtered = [trade for trade in filtered if trade.symbol == filters.symbol]
        if filters.session:
            filtered = [trade for trade in filtered if (trade.session or "Unknown") == filters.session]
        if filters.timeframe:
            filtered = [trade for trade in filtered if trade.timeframe == filters.timeframe]
        if filters.setup_id:
            filtered = [trade for trade in filtered if trade.setup_id == filters.setup_id]
        return filtered

    def _index(self, key_fn: Callable[[Trade], str]) -> dict[str, list[Trade]]:
        index: dict[str, list[Trade]] = defaultdict(list)
        for trade in self.trades:
            index[key_fn(trade)].append(trade)
        return dict(index)
