# Operations Runbook

Daily checks:

- `GET /health/ready`
- `GET /api/v1/operations/status`
- Confirm TradingView is `CONNECTED` or understand why it is `NEVER_CONNECTED`.
- Confirm Telegram is `CONNECTED` after the first successful delivery.
- Review recent rejections.

Pause signal intake:

```text
POST /api/v1/operations/pause
```

Resume signal intake:

```text
POST /api/v1/operations/resume
```

Troubleshooting:

- `INVALID_SECRET`: verify TradingView JSON secret and backend secret.
- `STALE_SIGNAL`: TradingView alert arrived later than `TRADINGVIEW_MAX_SIGNAL_AGE_SECONDS`.
- `ENTRY_DEVIATION_TOO_HIGH`: alert price moved too far from entry.
- `SYMBOL_DISABLED` or `TIMEFRAME_DISABLED`: update allow-list env vars.
- Telegram delivery failures: inspect `/metrics`, delivery history, and dead letters.

Known limitation:

In-process rate limits are suitable for one Render instance. Multi-instance deployments need a shared rate-limit store in a future phase.
