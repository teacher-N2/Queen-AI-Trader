# Changelog

## v0.9.0-personal-operations

- Added Phase 18B Personal Operations Mode.
- Added canonical TradingView webhook event contract support alongside existing webhook compatibility.
- Added symbol and timeframe normalization, signal age checks, entry deviation protection, safe rejection records, heartbeat status, pause/resume state, and protected operations endpoints.
- Added lightweight protected `/operations` dashboard.
- Added personal Telegram message formatting through the existing delivery subsystem.
- No broker execution, strategy changes, or Pine Script changes.
