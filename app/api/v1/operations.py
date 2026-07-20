from fastapi import APIRouter, Depends, HTTPException

from ...idempotency import idempotency_store
from ...operations import OperationsRejection, operations_service
from ...platform.dependencies import require_platform_permission
from ...platform.permissions import OPERATIONS_READ, OPERATIONS_RECOVERY_MANAGE
from ...platform.schemas import PageParams, envelope
from ...trade_registry import trade_registry

router = APIRouter()


@router.get("/status", summary="Personal operations status")
def status(principal=Depends(require_platform_permission(OPERATIONS_READ))):
    return envelope(operations_service.status())


@router.get("/connectivity", summary="TradingView and Telegram connectivity")
def connectivity(principal=Depends(require_platform_permission(OPERATIONS_READ))):
    return envelope(operations_service.connectivity())


@router.get("/signals/recent", summary="Recent operation signals")
def recent_signals(params: PageParams = Depends(), principal=Depends(require_platform_permission(OPERATIONS_READ))):
    return envelope([item.model_dump(mode="json") for item in operations_service.store.list_signals(limit=params.limit, offset=params.offset)])


@router.get("/signals/{signal_id}", summary="Signal details")
def signal_detail(signal_id: str, principal=Depends(require_platform_permission(OPERATIONS_READ))):
    record = operations_service.store.find_signal(signal_id)
    return envelope(record.model_dump(mode="json") if record else None)


@router.get("/trades/open", summary="Open trades")
def open_trades(principal=Depends(require_platform_permission(OPERATIONS_READ))):
    return envelope([trade.model_dump(mode="json") for trade in trade_registry.find_open_trades()])


@router.get("/trades/recent", summary="Recent trades")
def recent_trades(params: PageParams = Depends(), principal=Depends(require_platform_permission(OPERATIONS_READ))):
    trades = trade_registry.find_open_trades() + trade_registry.find_closed_trades()
    trades = sorted(trades, key=lambda item: item.updated_at, reverse=True)
    return envelope([trade.model_dump(mode="json") for trade in trades[params.offset : params.offset + params.limit]])


@router.get("/trades/{trade_id}", summary="Trade details")
def trade_detail(trade_id: str, principal=Depends(require_platform_permission(OPERATIONS_READ))):
    return envelope(trade_registry.find_trade(trade_id).model_dump(mode="json"))


@router.get("/deliveries/recent", summary="Recent delivery operations")
def recent_deliveries(params: PageParams = Depends(), principal=Depends(require_platform_permission(OPERATIONS_READ))):
    records = [record for record in idempotency_store.all_operations() if record.get("scope") == "delivery"]
    records = sorted(records, key=lambda item: item.get("updated_at") or 0, reverse=True)
    return envelope(records[params.offset : params.offset + params.limit])


@router.get("/rejections/recent", summary="Recent rejected signals")
def recent_rejections(params: PageParams = Depends(), principal=Depends(require_platform_permission(OPERATIONS_READ))):
    return envelope([item.model_dump(mode="json") for item in operations_service.store.list_rejections(limit=params.limit, offset=params.offset)])


@router.get("/configuration", summary="Safe personal operations configuration")
def configuration(principal=Depends(require_platform_permission(OPERATIONS_READ))):
    return envelope(operations_service.configuration())


@router.post("/pause", summary="Pause signal intake")
def pause(principal=Depends(require_platform_permission(OPERATIONS_RECOVERY_MANAGE))):
    try:
        return envelope(operations_service.pause(actor=principal.principal_id).model_dump(mode="json"))
    except OperationsRejection as exc:
        raise HTTPException(status_code=429 if exc.retryable else 400, detail=exc.code.value) from exc


@router.post("/resume", summary="Resume signal intake")
def resume(principal=Depends(require_platform_permission(OPERATIONS_RECOVERY_MANAGE))):
    try:
        return envelope(operations_service.resume(actor=principal.principal_id).model_dump(mode="json"))
    except OperationsRejection as exc:
        raise HTTPException(status_code=429 if exc.retryable else 400, detail=exc.code.value) from exc


@router.post("/test-telegram", summary="Send Telegram test message")
async def test_telegram(principal=Depends(require_platform_permission(OPERATIONS_RECOVERY_MANAGE))):
    try:
        return envelope(await operations_service.test_telegram("operations-api", actor=principal.principal_id))
    except OperationsRejection as exc:
        raise HTTPException(status_code=429 if exc.retryable else 400, detail=exc.code.value) from exc
