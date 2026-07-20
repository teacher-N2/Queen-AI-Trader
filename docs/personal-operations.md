# Personal Operations Mode

Queen AI Trader Personal Operations Mode is for one owner running TradingView alerts, Telegram notifications, and backend trade-state tracking. It does not place broker orders.

Flow:

1. Queen Engine sends a TradingView webhook.
2. The backend authenticates the shared secret.
3. The canonical payload is validated and normalized.
4. Accepted `SIGNAL_OPEN` events create or update a trade through the existing Trade State Engine.
5. Accepted lifecycle events update existing trades.
6. Telegram messages are sent through the existing durable delivery pipeline.
7. Operations status is persisted and available under `/api/v1/operations` and `/operations`.

Modes:

- `PAPER_SIGNAL`: live signal intake, manual execution or observation only.
- `LIVE_SIGNAL`: live signal delivery only; still no broker execution.
- `DISABLED`: personal signal mode disabled.

Pause states:

- `RUNNING`: signal intake active.
- `PAUSED`: heartbeats and lifecycle updates may continue; new `SIGNAL_OPEN` events are rejected safely.
- `MAINTENANCE`: operational intake is blocked.

Protected API endpoints require platform operations permissions.
