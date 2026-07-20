import asyncio
import html as html_lib
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from fastapi import Depends, FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .audit import audit_service
from .api.v1.router import router as api_v1_router
from .config import settings
from .errors import QueenGatewayError
from .gateway import queen_gateway
from .health import health_service
from .metrics import metrics
from .middleware import ProductionMiddleware
from .observability import configure_logging, log_event
from .production_errors import ProductionError
from .delivery_recovery import delivery_recovery_worker
from .platform.settings_repository import settings_repository
from .platform.services import bootstrap_service, platform_settings_service
from .platform.dependencies import require_platform_permission
from .platform.permissions import OPERATIONS_READ, OPERATIONS_RECOVERY_MANAGE
from .operations import operations_service
from .recovery import recovery_manager
from .runtime_context import get_context
from .runtime_state import runtime_state


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    settings.validate_startup()
    if settings.platform_enabled:
        platform_settings_service.defaults()
        bootstrap_service.bootstrap_from_settings()
    recovery_report = recovery_manager.recover()
    runtime_state.mark_started(recovery_report)
    app.state.delivery_recovery_task = asyncio.create_task(delivery_recovery_worker.recover_once(limit=settings.delivery_recovery_limit))
    log_event("application_started", status="ready")
    try:
        yield
    finally:
        runtime_state.mark_shutting_down()
        recovery_task = getattr(app.state, "delivery_recovery_task", None)
        if recovery_task and not recovery_task.done():
            try:
                await asyncio.wait_for(recovery_task, timeout=settings.shutdown_drain_timeout_seconds)
            except asyncio.TimeoutError:
                recovery_task.cancel()
        drain_report = await runtime_state.drain(settings.shutdown_drain_timeout_seconds)
        log_event(
            "application_shutdown",
            status="stopped",
            operation="shutdown",
            drain_status=drain_report.get("status"),
            pending_operations=drain_report.get("pending", 0),
            completed_operations=runtime_state.snapshot().get("completed_operations", 0),
            failed_operations=runtime_state.snapshot().get("failed_operations", 0),
            cancelled_operations=drain_report.get("cancelled", 0),
        )


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="Queen AI Trader gateway and Queen Platform Core API.",
    lifespan=lifespan,
)
app.add_middleware(ProductionMiddleware)
if settings.cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_methods=["POST", "GET", "PATCH", "DELETE"],
        allow_headers=[
            "authorization",
            "x-api-key",
            "x-request-id",
            "x-correlation-id",
            settings.webhook_secret_header,
            settings.webhook_signature_header,
            settings.webhook_timestamp_header,
            "content-type",
        ],
    )
if settings.allowed_hosts and "*" not in settings.allowed_hosts:
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=list(settings.allowed_hosts))
app.include_router(api_v1_router)


def error_response(status_code: int, error_code: str, message: str, *, retryable: bool = False, details: dict | None = None, path: str = "") -> JSONResponse:
    context = get_context()
    timestamp = datetime.now(UTC).isoformat()
    if path.startswith("/api/v1"):
        content = {
            "error": {
                "code": error_code,
                "message": message,
                "retryable": retryable,
            },
            "meta": {
                "request_id": context.request_id,
                "correlation_id": context.correlation_id,
                "timestamp": timestamp,
                "api_version": "v1",
            },
        }
        if settings.environment != "production" and details:
            content["error"]["details"] = details
        return JSONResponse(status_code=status_code, content=content)
    content = {
        "error_code": error_code,
        "message": message,
        "request_id": context.request_id,
        "correlation_id": context.correlation_id,
        "timestamp": timestamp,
        "retryable": retryable,
    }
    if settings.environment != "production" and details:
        content["details"] = details
    return JSONResponse(status_code=status_code, content=content)


@app.exception_handler(QueenGatewayError)
async def queen_gateway_error_handler(request: Request, exc: QueenGatewayError):
    context = get_context()
    metrics.increment("requests_failed_total")
    if exc.code in {"validation_error", "authentication_error"}:
        metrics.increment("signals_rejected_total")
    audit_service.record(
        "gateway_error",
        context.request_id,
        path=str(request.url.path),
        error_code=exc.code,
        status_code=exc.status_code,
    )
    retryable = getattr(exc, "retryable", False)
    message = getattr(exc, "safe_message", exc.message if settings.environment != "production" else "request failed")
    return error_response(exc.status_code, exc.code, message, retryable=retryable, details={"detail": exc.message}, path=str(request.url.path))


@app.exception_handler(ProductionError)
async def production_error_handler(request: Request, exc: ProductionError):
    context = get_context()
    metrics.increment("requests_failed_total")
    audit_service.record("production_error", context.request_id, path=str(request.url.path), error_code=exc.code)
    return error_response(exc.status_code, exc.code, exc.safe_message, retryable=exc.retryable, path=str(request.url.path))


@app.exception_handler(Exception)
async def unhandled_error_handler(request: Request, exc: Exception):
    context = get_context()
    metrics.increment("requests_failed_total")
    audit_service.record(
        "unhandled_error",
        context.request_id,
        path=str(request.url.path),
        error_type=exc.__class__.__name__,
    )
    return error_response(500, "internal_error", "internal service error", path=str(request.url.path))


@app.middleware("http")
async def platform_maintenance_middleware(request: Request, call_next):
    path = request.url.path
    if settings.platform_enabled and path.startswith("/api/v1") and not path.startswith("/api/v1/system"):
        maintenance = settings_repository.get("maintenance_mode")
        if maintenance and bool(maintenance.value):
            return error_response(503, "maintenance_mode", "platform maintenance mode is active", retryable=True, path=path)
    return await call_next(request)


@app.get("/")
def health():
    return health_service.live()


@app.get("/health")
def health_root():
    return {
        "live": health_service.live(),
        "ready": health_service.ready(),
    }


@app.get("/health/live")
def health_live():
    return health_service.live()


@app.get("/health/ready")
def health_ready():
    result = health_service.ready()
    status_code = 503 if result["status"] == "unhealthy" else 200
    return JSONResponse(status_code=status_code, content=result)


@app.get("/metrics")
def metrics_snapshot():
    snapshot = metrics.snapshot()
    from .circuit_breaker import telegram_circuit_breaker

    snapshot["circuit_breakers"] = {"telegram": telegram_circuit_breaker.snapshot()}
    snapshot["runtime"] = runtime_state.snapshot()
    return snapshot


@app.get("/operations", response_class=HTMLResponse)
def operations_dashboard(principal=Depends(require_platform_permission(OPERATIONS_READ))):
    if not settings.operations_dashboard_enabled:
        return HTMLResponse("<h1>Operations dashboard disabled</h1>", status_code=404)
    status = operations_service.status()
    signals = operations_service.store.list_signals(limit=10)
    rejections = operations_service.store.list_rejections(limit=10)
    open_trades = status["today"]["open_trades"]
    def e(value) -> str:
        return html_lib.escape(str(value if value is not None else "-"))
    html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta http-equiv="refresh" content="20">
  <title>Queen AI Trader Operations</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 0; background: #f7f7f4; color: #20231f; }}
    header, section {{ padding: 16px; max-width: 980px; margin: auto; }}
    header {{ background: #20231f; color: white; max-width: none; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 10px; }}
    .card {{ background: white; border: 1px solid #d7d8d2; border-radius: 6px; padding: 12px; }}
    .ok {{ color: #0f7a3b; }} .warn {{ color: #a36700; }} .bad {{ color: #b42318; }} .muted {{ color: #666; }}
    table {{ width: 100%; border-collapse: collapse; background: white; }}
    th, td {{ text-align: left; border-bottom: 1px solid #e5e5df; padding: 8px; font-size: 14px; }}
    button {{ padding: 8px 12px; border: 1px solid #999; border-radius: 4px; background: white; }}
  </style>
</head>
<body>
  <header><h1>Queen AI Trader Operations</h1><p>Mode: {e(status["mode"])} | State: {e(status["system_status"])}</p></header>
  <section class="grid">
    <div class="card"><strong>TradingView</strong><br><span class="{'ok' if status['tradingview']['status'] == 'CONNECTED' else 'warn'}">{e(status['tradingview']['status'])}</span><br><small>{e(status['tradingview']['last_signal_at'] or 'never')}</small></div>
    <div class="card"><strong>Telegram</strong><br><span class="{'ok' if status['telegram']['status'] == 'CONNECTED' else 'warn'}">{e(status['telegram']['status'])}</span><br><small>{e(status['telegram']['last_success_at'] or 'no delivery yet')}</small></div>
    <div class="card"><strong>Signals Today</strong><br>{e(status['today']['signals_received'])} received<br>{e(status['today']['signals_rejected'])} rejected</div>
    <div class="card"><strong>Trades</strong><br>{e(open_trades)} open<br>{e(status['today']['closed_trades'])} closed</div>
  </section>
  <section>
    <h2>Recent Signals</h2>
    <table><tr><th>Signal</th><th>Symbol</th><th>Side</th><th>Decision</th><th>Trade</th></tr>
    {''.join(f'<tr><td>{e(s.signal_id)}</td><td>{e(s.symbol)}</td><td>{e(s.side)}</td><td>{e(s.decision)}</td><td>{e(s.trade_id)}</td></tr>' for s in signals)}
    </table>
  </section>
  <section>
    <h2>Recent Rejections</h2>
    <table><tr><th>Signal</th><th>Code</th><th>Time</th></tr>
    {''.join(f'<tr><td>{e(r.signal_id)}</td><td>{e(r.code)}</td><td>{e(r.received_at)}</td></tr>' for r in rejections)}
    </table>
  </section>
</body>
</html>"""
    return HTMLResponse(html)


@app.post("/webhook/tradingview")
async def tradingview_webhook(request: Request):
    return await queen_gateway.handle_tradingview(request)
