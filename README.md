Queen AI Trader v0.2

This server version removes the second Queen Score calculation from Render.
TradingView Queen Engine decides BUY or SELL.
Render validates the levels, applies the daily trade limit, and sends the trade to Telegram.

Replace:
- app/main.py
- app/telegram.py
