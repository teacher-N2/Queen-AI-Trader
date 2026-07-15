from fastapi import FastAPI, HTTPException

from .config import TRADINGVIEW_WEBHOOK_SECRET
from .models import TradingSignal
from .scoring import calculate_score
from .risk import can_send_new_trade, append_log
from .telegram import send_telegram

app = FastAPI(title="Queen AI Trader", version="0.1.0")

@app.get("/")
def health():
    return {"status": "online", "service": "Queen AI Trader"}

@app.post("/webhook/tradingview")
async def tradingview_webhook(signal: TradingSignal):
    if not TRADINGVIEW_WEBHOOK_SECRET:
        raise HTTPException(status_code=500, detail="Webhook secret غير مضبوط")

    if signal.secret != TRADINGVIEW_WEBHOOK_SECRET:
        raise HTTPException(status_code=401, detail="Webhook secret غير صحيح")

    result = calculate_score(signal)

    if not result.accepted:
        append_log({
            "event": "signal_rejected",
            "queen_score": result.queen_score,
            "grade": result.grade,
            "signal": signal.model_dump(),
            "reason": result.rejection_reason,
        })
        return result

    allowed, reason = can_send_new_trade()
    if not allowed:
        append_log({
            "event": "signal_blocked_by_risk",
            "queen_score": result.queen_score,
            "signal": signal.model_dump(),
            "reason": reason,
        })
        raise HTTPException(status_code=429, detail=reason)

    telegram_result = await send_telegram(result)

    append_log({
        "event": "signal_sent",
        "queen_score": result.queen_score,
        "grade": result.grade,
        "signal": signal.model_dump(),
        "delivery": telegram_result,
    })

    return {
        "accepted": True,
        "queen_score": result.queen_score,
        "grade": result.grade,
        "delivery": telegram_result,
    }
