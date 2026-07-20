try:
    import httpx
except ModuleNotFoundError:
    httpx = None  # type: ignore[assignment]

from .circuit_breaker import telegram_circuit_breaker
from .config import settings
from .models import MessageEnvelope, ScoredSignal


class TelegramService:
    def __init__(self) -> None:
        self.token = settings.telegram_bot_token
        self.chat_ids = list(settings.telegram_chat_ids)

    def configured(self) -> bool:
        return bool(self.token and self.chat_ids)

    async def send_message(self, chat_id: str, message: MessageEnvelope) -> dict:
        if not self.token:
            return {"sent": False, "reason": "telegram bot token is not configured"}
        if httpx is None:
            return {"sent": False, "reason": "httpx dependency is not installed"}
        telegram_circuit_breaker.before_call()
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": message.body,
            "parse_mode": settings.telegram_parse_mode,
            "disable_web_page_preview": True,
        }
        async with httpx.AsyncClient(timeout=settings.request_timeout_seconds) as client:
            try:
                response = await client.post(url, json=payload)
                response.raise_for_status()
                telegram_circuit_breaker.record_success()
                return {"sent": True, "telegram_response": response.json()}
            except Exception as exc:
                telegram_circuit_breaker.record_failure(exc)
                raise

    async def broadcast(self, message: MessageEnvelope, destinations: list[str] | None = None) -> list[dict]:
        chat_ids = destinations or self.chat_ids
        if not chat_ids:
            return [{"sent": False, "reason": "no telegram chat destinations configured"}]
        results: list[dict] = []
        for chat_id in chat_ids:
            result = await self.send_message(chat_id, message)
            results.append({"chat_id": "[redacted]", **result})
        return results


telegram_service = TelegramService()


def format_signal(result: ScoredSignal) -> str:
    signal = result.signal
    return (
        "Queen AI Trader\n\n"
        f"{signal.side} {signal.symbol} | {signal.timeframe}\n"
        f"Entry: {signal.entry}\n"
        f"SL: {signal.stop_loss}\n"
        f"TP1: {signal.take_profit_1}\n"
        f"TP2: {signal.take_profit_2 or '-'}\n"
        f"TP3: {signal.take_profit_3 or '-'}\n"
        f"RR: 1:{signal.rr}\n"
        f"Queen Score: {result.queen_score}/100 ({result.grade})\n\n"
        "Analysis alert only. No profit is guaranteed."
    )


async def send_telegram(result: ScoredSignal):
    # Legacy compatibility helper for the old MVP flow.
    if not telegram_service.configured():
        return {"sent": False, "reason": "telegram is not configured"}
    text = format_signal(result)
    class LegacyEnvelope:
        body = text
    results = []
    for chat_id in telegram_service.chat_ids:
        results.append(await telegram_service.send_message(chat_id, LegacyEnvelope()))  # type: ignore[arg-type]
    return {"sent": any(item.get("sent") for item in results), "results": results}
