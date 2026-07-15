import httpx
from .config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
from .models import ScoredSignal

def format_signal(result: ScoredSignal) -> str:
    s = result.signal
    return (
        "👑 Queen AI Trader\n\n"
        f"{s.side} {s.symbol} | {s.timeframe}\n"
        f"Entry: {s.entry}\n"
        f"SL: {s.stop_loss}\n"
        f"TP1: {s.take_profit_1}\n"
        f"TP2: {s.take_profit_2 or '-'}\n"
        f"TP3: {s.take_profit_3 or '-'}\n"
        f"RR: 1:{s.rr}\n"
        f"Queen Score: {result.queen_score}/100 ({result.grade})\n\n"
        f"Liquidity Sweep: {'✅' if s.liquidity_sweep else '❌'}\n"
        f"MSS: {'✅' if s.mss else '❌'}\n"
        f"FVG: {'✅' if s.fvg else '❌'}\n"
        f"Order Block: {'✅' if s.order_block else '❌'}\n"
        f"Session: {s.session}\n\n"
        "هذه إشارة تحليلية وليست ضمانًا للربح."
    )

async def send_telegram(result: ScoredSignal):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return {"sent": False, "reason": "Telegram غير مهيأ"}

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": format_signal(result)}

    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.post(url, json=payload)
        response.raise_for_status()
        return {"sent": True, "telegram_response": response.json()}
