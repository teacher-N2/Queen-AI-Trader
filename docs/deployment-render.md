# Render Deployment

Render uses `render.yaml` with:

- Build command: `pip install -r requirements.txt`
- Start command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
- Health path: `/health/ready`

Set secrets in the Render dashboard:

- `WEBHOOK_SHARED_SECRET` or `TRADINGVIEW_WEBHOOK_SECRET`
- `ACCESS_TOKEN_SECRET`
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_DEFAULT_CHAT_ID` or `TELEGRAM_CHAT_IDS`

Recommended personal operations values:

- `PERSONAL_OPERATIONS_MODE=true`
- `PAPER_SIGNAL_MODE=PAPER_SIGNAL`
- `SIGNALS_ENABLED=true`
- `TRADE_UPDATES_ENABLED=true`
- `OPERATIONS_DASHBOARD_ENABLED=true`

Use a persistent disk for `STORAGE_DIR` so trade state, idempotency, delivery history, and operations state survive restarts. Do not commit real secrets.
