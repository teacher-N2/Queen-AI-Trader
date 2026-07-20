# TradingView Setup

1. Add Queen Engine to the desired chart.
2. Choose the symbol.
3. Choose the timeframe.
4. Create a TradingView alert.
5. Set the webhook URL to `https://YOUR-DOMAIN/webhook/tradingview`.
6. Use the canonical JSON message from `docs/webhook-contract.md`.
7. Insert the configured webhook secret in the `secret` field.
8. Use alert frequency compatible with Queen Engine non-repainting behavior.
9. Repeat for each desired chart, symbol, or timeframe.
10. Configure a heartbeat alert if supported.
11. Test with a controlled signal.
12. Confirm receipt in Telegram and `/api/v1/operations/status`.

TradingView alerts run from TradingView servers. Your computer and browser do not need to remain open, but the backend must remain deployed and reachable.
