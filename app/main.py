from fastapi import FastAPI, HTTPException

from .config import TRADINGVIEW_WEBHOOK_SECRET
from .models import TradingSignal
from .risk import can_send_new_trade, append_log
from .telegram import send_telegram

app = FastAPI(title="Queen AI Trader", version="0.2.0")

@app.get("/")
def health():
    return {"status": "online", "service": "Queen AI Trader", "version": "0.2.0"}

def validate_trade_logic(signal: TradingSignal) -> None:
    if signal.side == "BUY":
        if not (signal.stop_loss < signal.entry < signal.take_profit_1):
            raise HTTPException(status_code=422, detail="Invalid BUY levels")
    else:
        if not (signal.take_profit_1 < signal.entry < signal.stop_loss):
            raise HTTPException(status_code=422, detail="Invalid SELL levels")
    if signal.rr < 1.0:
        raise HTTPException(status_code=422, detail="RR must be at least 1:1")

@app.post("/webhook/tradingview")
async def tradingview_webhook(signal: TradingSignal):
    if not TRADINGVIEW_WEBHOOK_SECRET:
        raise HTTPException(status_code=500, detail="Webhook secret is not configured")
    if signal.secret != TRADINGVIEW_WEBHOOK_SECRET:
        raise HTTPException(status_code=401, detail="Invalid webhook secret")

    validate_trade_logic(signal)

    allowed, reason = can_send_new_trade()
    if not allowed:
        raise HTTPException(status_code=429, detail=reason)

    delivery = await send_telegram(signal)

    append_log({
        "event": "signal_sent",
        "decision_source": "queen_engine",
        "signal": signal.model_dump(exclude={"secret"}),
        "delivery": delivery,
    })

    return {"accepted": True, "decision_source": "queen_engine", "delivery": delivery}
