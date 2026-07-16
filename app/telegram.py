import httpx

from .config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
from .models import TradingSignal

def format_signal(s: TradingSignal) -> str:
    icon = "🟢" if s.side == "BUY" else "🔴"
    return (
        "👑 QUEEN AI TRADER\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"{icon} {s.side} {s.symbol}\n"
        f"⏱ Timeframe: {s.timeframe}\n"
        f"🌍 Session: {s.session}\n\n"
        f"📍 Entry: {s.entry}\n"
        f"🛑 SL: {s.stop_loss}\n"
        f"🎯 TP1: {s.take_profit_1}\n"
        f"🎯 TP2: {s.take_profit_2 or '-'}\n"
        f"🎯 TP3: {s.take_profit_3 or '-'}\n"
        f"⚖️ RR: 1:{s.rr}\n\n"
        f"Liquidity Sweep: {'✅' if s.liquidity_sweep else '▫️'}\n"
        f"MSS: {'✅' if s.mss else '▫️'}\n"
        f"FVG: {'✅' if s.fvg else '▫️'}\n"
        f"Order Block: {'✅' if s.order_block else '▫️'}\n\n"
        f"📝 {s.notes or 'Queen Engine signal'}\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "إشارة تحليلية وليست ضمانًا للربح."
    )

async def send_telegram(signal: TradingSignal):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return {"sent": False, "reason": "Telegram is not configured"}

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.post(url, json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": format_signal(signal),
        })
        response.raise_for_status()
        return {"sent": True, "telegram_response": response.json()}
