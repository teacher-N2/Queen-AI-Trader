# Telegram Setup

Required:

- `TELEGRAM_ENABLED=true`
- `TELEGRAM_BOT_TOKEN`
- At least one destination: `TELEGRAM_DEFAULT_CHAT_ID` or `TELEGRAM_CHAT_IDS`

Optional routing:

- `TELEGRAM_SCALP_CHAT_ID`
- `TELEGRAM_INTRADAY_CHAT_ID`
- `TELEGRAM_SWING_CHAT_ID`
- `TELEGRAM_ERROR_CHAT_ID`

Routing falls back to `TELEGRAM_DEFAULT_CHAT_ID` when a style-specific chat is absent.

Use `POST /api/v1/operations/test-telegram` to send a safe test message through the existing delivery pipeline. The bot token is never returned by API responses.
