from .trade_registry import TradeRegistry, trade_registry
from .trade_state import Trade, TradeLifecycleState


class TradeQueryService:
    def __init__(self, registry: TradeRegistry = trade_registry):
        self.registry = registry

    def findTrade(self, trade_id: str) -> Trade:
        return self.registry.find_trade(trade_id)

    def findTradesByState(self, state: TradeLifecycleState) -> list[Trade]:
        return self.registry.find_trades_by_state(state)

    def findOpenTrades(self) -> list[Trade]:
        return self.registry.find_open_trades()

    def findClosedTrades(self) -> list[Trade]:
        return self.registry.find_closed_trades()

    def findTradeHistory(self, trade_id: str) -> list[dict]:
        return self.registry.find_trade_history(trade_id)

    def findTradesBySymbol(self, symbol: str) -> list[Trade]:
        return self.registry.find_trades_by_symbol(symbol)

    def findTradesBySession(self, session: str) -> list[Trade]:
        return self.registry.find_trades_by_session(session)


trade_queries = TradeQueryService()
