from .errors import QueenGatewayError


class TradeStateError(QueenGatewayError):
    status_code = 409
    code = "trade_state_error"


class InvalidTransitionError(TradeStateError):
    code = "invalid_trade_transition"


class TradeNotFoundError(TradeStateError):
    status_code = 404
    code = "trade_not_found"


class TradeAlreadyClosedError(TradeStateError):
    code = "trade_already_closed"


class DuplicateEventError(TradeStateError):
    code = "duplicate_trade_event"


class StateConflictError(TradeStateError):
    code = "trade_state_conflict"
