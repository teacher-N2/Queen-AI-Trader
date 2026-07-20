from collections import defaultdict

from .trade_errors import TradeNotFoundError
from .trade_history import TradeHistoryStore, trade_history_store
from .trade_state import Trade, TradeLifecycleState


class TradeRegistry:
    def __init__(self, history_store: TradeHistoryStore = trade_history_store):
        self.history_store = history_store
        self._trades: dict[str, Trade] = {}
        self._by_signal_id: dict[str, set[str]] = defaultdict(set)
        self._by_symbol: dict[str, set[str]] = defaultdict(set)
        self._by_state: dict[TradeLifecycleState, set[str]] = defaultdict(set)
        self._by_session: dict[str, set[str]] = defaultdict(set)
        self._by_entry_id: dict[str, set[str]] = defaultdict(set)
        self.recover()

    def recover(self) -> None:
        self._clear_indexes()
        for trade in self.history_store.load_latest_trades().values():
            self._trades[trade.trade_id] = trade
            self._index_trade(trade)

    def upsert(self, trade: Trade) -> None:
        if trade.trade_id in self._trades:
            self._remove_trade_id_from_indexes(trade.trade_id)
        self._trades[trade.trade_id] = trade
        self._index_trade(trade)
        self.history_store.save_trade(trade)

    def find_trade(self, trade_id: str) -> Trade:
        trade = self._trades.get(trade_id)
        if not trade:
            raise TradeNotFoundError(f"trade not found: {trade_id}")
        return trade

    def exists(self, trade_id: str) -> bool:
        return trade_id in self._trades

    def find_trades_by_state(self, state: TradeLifecycleState) -> list[Trade]:
        return self._resolve(self._by_state.get(state, set()))

    def find_open_trades(self) -> list[Trade]:
        closed = {
            TradeLifecycleState.STOPPED,
            TradeLifecycleState.INVALIDATED,
            TradeLifecycleState.EXPIRED,
            TradeLifecycleState.CLOSED,
        }
        trade_ids: set[str] = set()
        for state, indexed_ids in self._by_state.items():
            if state not in closed:
                trade_ids.update(indexed_ids)
        return self._resolve(trade_ids)

    def find_closed_trades(self) -> list[Trade]:
        closed = {
            TradeLifecycleState.STOPPED,
            TradeLifecycleState.INVALIDATED,
            TradeLifecycleState.EXPIRED,
            TradeLifecycleState.CLOSED,
        }
        trade_ids: set[str] = set()
        for state in closed:
            trade_ids.update(self._by_state.get(state, set()))
        return self._resolve(trade_ids)

    def find_trades_by_symbol(self, symbol: str) -> list[Trade]:
        return self._resolve(self._by_symbol.get(symbol, set()))

    def find_trades_by_session(self, session: str) -> list[Trade]:
        return self._resolve(self._by_session.get(session, set()))

    def find_trades_by_signal(self, signal_id: str) -> list[Trade]:
        return self._resolve(self._by_signal_id.get(signal_id, set()))

    def find_trades_by_entry(self, entry_id: str) -> list[Trade]:
        return self._resolve(self._by_entry_id.get(entry_id, set()))

    def find_trade_history(self, trade_id: str) -> list[dict]:
        self.find_trade(trade_id)
        return self.history_store.load_trade_history(trade_id)

    def _resolve(self, trade_ids: set[str]) -> list[Trade]:
        return [self._trades[trade_id] for trade_id in trade_ids if trade_id in self._trades]

    def _clear_indexes(self) -> None:
        self._trades.clear()
        self._by_signal_id.clear()
        self._by_symbol.clear()
        self._by_state.clear()
        self._by_session.clear()
        self._by_entry_id.clear()

    def _index_trade(self, trade: Trade) -> None:
        self._by_signal_id[trade.signal_id].add(trade.trade_id)
        self._by_symbol[trade.symbol].add(trade.trade_id)
        self._by_state[trade.current_state].add(trade.trade_id)
        if trade.session:
            self._by_session[trade.session].add(trade.trade_id)
        if trade.entry_id:
            self._by_entry_id[trade.entry_id].add(trade.trade_id)

    def _remove_trade_id_from_indexes(self, trade_id: str) -> None:
        for index in (
            self._by_signal_id,
            self._by_symbol,
            self._by_state,
            self._by_session,
            self._by_entry_id,
        ):
            for indexed_ids in index.values():
                indexed_ids.discard(trade_id)


trade_registry = TradeRegistry()
