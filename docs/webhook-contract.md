# TradingView Webhook Contract

Webhook URL:

```text
https://YOUR-DOMAIN/webhook/tradingview
```

Supported `event_type` values:

- `SIGNAL_OPEN`
- `TRADE_ACTIVATED`
- `TP_HIT`
- `SL_HIT`
- `TRADE_CLOSED`
- `TRADE_CANCELLED`
- `TRADE_EXPIRED`
- `HEARTBEAT`

Canonical payload:

```json
{
  "schema_version": "1.0",
  "event_type": "SIGNAL_OPEN",
  "source": "QUEEN_ENGINE",
  "secret": "<webhook-secret>",
  "alert_id": "unique-alert-id",
  "signal_id": "unique-signal-id",
  "trade_id": null,
  "symbol": "XAUUSD",
  "exchange": "OANDA",
  "timeframe": "5",
  "side": "BUY",
  "setup_type": "ICT_2022",
  "entry_type": "MARKET",
  "entry": 3378.4,
  "stop_loss": 3374.9,
  "take_profits": [
    {"level": 1, "price": 3382.0},
    {"level": 2, "price": 3385.5},
    {"level": 3, "price": 3390.2}
  ],
  "confidence": 87,
  "session": "LONDON",
  "direction_bias": "BULLISH",
  "signal_timestamp": "2026-07-21T09:20:00Z",
  "bar_timestamp": "2026-07-21T09:15:00Z",
  "price_at_alert": 3378.6,
  "risk_percent": 1.0,
  "mode": "PAPER_SIGNAL",
  "metadata": {
    "chart_symbol": "{{ticker}}",
    "chart_timeframe": "{{interval}}"
  }
}
```

Validation rejects unsupported schemas, invalid event types, stale or future signals, invalid directions, impossible price structures, duplicate `signal_id` or `alert_id`, invalid secrets, disabled symbols or timeframes, low confidence, and excessive entry deviation.

The raw secret is never stored in operation signal records.
