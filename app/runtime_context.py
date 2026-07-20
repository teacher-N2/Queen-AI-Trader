from contextvars import ContextVar
from dataclasses import dataclass
from uuid import uuid4


@dataclass(frozen=True)
class RequestContext:
    request_id: str
    correlation_id: str
    signal_id: str | None = None
    trade_id: str | None = None
    event_id: str | None = None
    delivery_id: str | None = None


_context: ContextVar[RequestContext | None] = ContextVar("queen_request_context", default=None)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


def get_context() -> RequestContext:
    current = _context.get()
    if current:
        return current
    return RequestContext(request_id="unavailable", correlation_id="unavailable")


def set_context(context: RequestContext):
    return _context.set(context)


def reset_context(token) -> None:
    _context.reset(token)


def update_context(**fields: str | None) -> RequestContext:
    current = get_context()
    updated = RequestContext(
        request_id=fields.get("request_id") or current.request_id,
        correlation_id=fields.get("correlation_id") or current.correlation_id,
        signal_id=fields.get("signal_id") or current.signal_id,
        trade_id=fields.get("trade_id") or current.trade_id,
        event_id=fields.get("event_id") or current.event_id,
        delivery_id=fields.get("delivery_id") or current.delivery_id,
    )
    _context.set(updated)
    return updated
