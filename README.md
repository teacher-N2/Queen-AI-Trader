# Queen AI Trader — MVP

نسخة أولية لوكيل تداول خاص بالذهب XAUUSD.

## ماذا تفعل هذه النسخة؟
- تستقبل تنبيهات TradingView عبر Webhook.
- تتحقق من كلمة مرور التنبيه.
- تحسب Queen Score من 100.
- ترفض الإشارات الضعيفة.
- ترسل الإشارات المقبولة إلى Telegram.
- تحفظ كل إشارة في سجل JSONL.
- تضع حدودًا يومية للمخاطرة وعدد الصفقات.

## مهم
هذه النسخة لا تنفذ صفقات تلقائيًا، ولا تضمن الربح. هي نظام تحليل وتنبيه ومراقبة مخاطر.

## التشغيل المحلي
1. ثبتي Python 3.11 أو أحدث.
2. انسخي `.env.example` إلى `.env`.
3. ضعي القيم المطلوبة.
4. نفذي:
   pip install -r requirements.txt
   uvicorn app.main:app --reload --port 8000

## ربط TradingView
استخدمي رابط:
https://YOUR-DOMAIN/webhook/tradingview

وضعي رسالة التنبيه بصيغة JSON مطابقة للنموذج الموجود في:
tradingview_alert_example.json

## Queen Engine for TradingView
The first Pine Script version lives in `pine/QueenEngine.pine`.

Setup:
1. Open TradingView, then open the Pine Editor.
2. Copy the full contents of `pine/QueenEngine.pine` into the editor.
3. Save it as `Queen Engine v1`, then click Add to chart.
4. Use it only on XAUUSD or US100 charts.
5. Use 5m for Scalping mode, or 15m/1h for Intraday mode.
6. In the indicator settings, set `Webhook secret` to the same value as `TRADINGVIEW_WEBHOOK_SECRET`.
7. Create an alert from the indicator and choose `Any alert() function call`.
8. Enable Webhook URL and use:
   `https://queen-ai-trader.onrender.com/webhook/tradingview`

The script sends JSON fields matching the FastAPI `TradingSignal` model:
`secret`, `symbol`, `timeframe`, `side`, `entry`, `stop_loss`, `take_profit_1`, `take_profit_2`, `take_profit_3`, `liquidity_sweep`, `mss`, `fvg`, `order_block`, `session`, `rr`, and `notes`.

Queen Engine uses a weighted decision score from trend, market structure, liquidity, momentum, volatility, session timing, and optional FVG / Order Block confirmations. FVG and Order Block can improve the score but are not required. This is an analysis and alerting tool only; it does not guarantee profitable trades.

## Phase 14 Backend Integration Layer

The backend is now a gateway and notification system only. It does not score trades, perform market analysis, place orders, or change Queen Engine decisions.

Architecture:

1. TradingView webhook receives the Queen Engine payload.
2. Queen Gateway authenticates, validates, and expands batch payloads.
3. Replay protection prevents duplicate processing.
4. Routing chooses notification route and destination group.
5. Message Builder creates readable Telegram Markdown.
6. Delivery Engine sends through Telegram with retry and dead-letter recording.
7. Audit and JSONL persistence record processing, delivery, and failures.

Required environment variables:

- `WEBHOOK_SHARED_SECRET`: shared secret used in the `X-Queen-Secret` header or the webhook JSON `secret` field.
- `TELEGRAM_BOT_TOKEN`: Telegram bot token.
- `TELEGRAM_CHAT_IDS`: comma-separated Telegram chat IDs.

Optional environment variables:

- `REQUIRE_WEBHOOK_SIGNATURE`: set `true` to require HMAC signatures.
- `WEBHOOK_SIGNATURE_SECRET`: HMAC secret.
- `WEBHOOK_TIMESTAMP_TOLERANCE_SECONDS`: default `300`.
- `ALLOWED_SCHEMA_VERSIONS`: default `1.0`.
- `STORAGE_DIR`: default `data`.
- `DELIVERY_MAX_ATTEMPTS`: default `3`.

TradingView webhook URL:

```text
https://YOUR-DOMAIN/webhook/tradingview
```

Render deployment is described in `render.yaml`. Set all secret values from the Render dashboard; do not commit secrets.

## Phase 15 Trade State Engine

The backend now maintains an authoritative Trade State Engine after a Queen Engine event enters the webhook gateway. This layer consumes backend events only; it does not generate TradingView signals, place broker orders, perform AI analysis, or alter Pine trading logic.

Trade lifecycle states:

```text
CREATED -> QUALIFIED -> ENTRY_READY -> ENTRY_EXECUTED -> OPEN
OPEN -> PARTIAL_EXIT | BREAK_EVEN | STOP_UPDATED | TARGET_1
TARGET_1 -> TARGET_2 -> TARGET_3 -> CLOSED
Any active state -> STOPPED | INVALIDATED | EXPIRED
STOPPED | INVALIDATED | EXPIRED -> CLOSED
```

Trade state files are stored as JSONL under `STORAGE_DIR`:

- `trade_snapshots.jsonl`: latest persisted trade snapshots for restart recovery.
- `trade_history.jsonl`: append-only transition history.

The query service in `app.trade_queries` exposes:

- `findTrade(trade_id)`
- `findTradesByState(state)`
- `findOpenTrades()`
- `findClosedTrades()`
- `findTradeHistory(trade_id)`
- `findTradesBySymbol(symbol)`
- `findTradesBySession(session)`

## Phase 16 Analytics & Intelligence Engine

The Analytics Engine is a read-only intelligence layer. It consumes existing backend data from trade snapshots, trade history, delivery history, audit logs, and signal metadata. It never generates signals, never changes trading decisions, and never mutates trade state.

Analytics modules:

- `app.analytics_engine`: report orchestration and source fingerprint caching.
- `app.analytics_storage`: read-only access to JSONL backend data plus analytics-only cache/export files.
- `app.analytics_metrics`: performance, risk, lifecycle, event, setup, and quality calculations.
- `app.analytics_registry`: in-memory grouping by session, symbol, timeframe, and setup.
- `app.analytics_reports`: structured report generation.
- `app.analytics_queries`: query API for application use.
- `app.analytics_export`: JSON and CSV export.
- `app.analytics_errors`: dedicated analytics errors.

Query examples:

- `getOverallStatistics()`
- `getSessionStatistics()`
- `getSymbolStatistics()`
- `getTimeframeStatistics()`
- `getTradeStatistics()`
- `getLifecycleStatistics()`
- `getEventStatistics()`

Exports support JSON and CSV. PDF and Excel are reserved for future phases.

## Phase 17 Production Hardening

Queen-AI-Trader now includes production hardening infrastructure around the existing gateway, trade state, delivery, and analytics layers. This phase does not change Pine Script, signal generation, trade logic, Telegram message formatting, or analytics formulas.

Production architecture:

1. FastAPI middleware creates `request_id` and `correlation_id`.
2. Gateway authenticates, validates, checks replay/idempotency, updates trade state, routes, and delivers.
3. Trade state transitions are protected by keyed locks.
4. Telegram delivery is guarded by idempotency, bounded retries, dead letters, and a circuit breaker.
5. Audit, persistence, metrics, health, readiness, and recovery provide operational visibility.

Startup flow:

- Configure structured logging.
- Validate storage availability.
- Recover persisted trade registry state.
- Rebuild trade indexes.
- Validate analytics storage readability.
- Mark readiness only after recovery completes.

Shutdown flow:

- Stop accepting new runtime work.
- Emit shutdown summary logs.
- Keep persisted JSONL state intact for restart recovery.

Health endpoints:

- `GET /health/live`: process liveness only.
- `GET /health/ready`: readiness with dependency-level checks.
- `GET /health`: combined liveness and readiness snapshot.
- `GET /metrics`: safe internal runtime metrics snapshot.

Operational behavior:

- Structured logs are JSON by default and redact secrets, tokens, signatures, and authorization-like fields.
- Error responses include `error_code`, `message`, `request_id`, `correlation_id`, `timestamp`, and `retryable`.
- Request body size is bounded by `MAX_REQUEST_BODY_BYTES`.
- CORS and trusted hosts are configured from environment variables.
- Delivery retries are bounded and do not retry validation, authentication, duplicate, or invalid-state errors.
- Telegram circuit breaker supports `CLOSED`, `OPEN`, and `HALF_OPEN`.
- Idempotency records survive restarts in `idempotency_records.jsonl`.
- Webhook operations use durable states: `RECEIVED`, `PROCESSING`, `COMPLETED`, `FAILED_RETRYABLE`, and `FAILED_PERMANENT`.
- Delivery operations use durable states: `PENDING`, `IN_PROGRESS`, `RETRY_SCHEDULED`, `DELIVERED`, `FAILED`, `DEAD_LETTERED`, and `CANCELLED`.
- Only `COMPLETED` webhooks and `DELIVERED` deliveries are treated as successful duplicates.
- `WEBHOOK_OPERATION_LEASE_SECONDS` and `DELIVERY_OPERATION_LEASE_SECONDS` control stale in-progress recovery.
- Dead letters are stored in `dead_letters.jsonl` with sanitized payload references and manual replay eligibility.
- Corrupt JSONL lines are quarantined during recovery instead of silently deleting full state.

Production checklist:

- Set `ENVIRONMENT=production`.
- Set `WEBHOOK_SHARED_SECRET`.
- Set `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_IDS` when Telegram is enabled.
- Set restrictive `ALLOWED_HOSTS`.
- Keep `ALLOW_UNSAFE_WILDCARD_HOSTS=false` in production.
- Set `CORS_ORIGINS` only if browser clients need it.
- Keep `DEBUG=false`.
- Use `LOG_FORMAT=json` in production.
- Monitor `/health/ready` and `/metrics`.
- Review `dead_letters.jsonl` after delivery failures.
- Back up the `STORAGE_DIR` directory before manual recovery work.

Local validation commands:

```bash
python -m compileall app tests
python -m unittest tests.test_production_hardening tests.test_analytics tests.test_trade_state
python -m pytest tests
```

`pytest` is listed in `requirements.txt`. The bundled Codex runtime used during implementation did not include installed project dependencies, so endpoint tests skip locally when FastAPI is unavailable.

## Phase 18A Queen Platform Core

Queen Platform Core adds the application foundation for multi-user, multi-workspace operation while preserving the existing TradingView webhook, trade state semantics, analytics formulas, Telegram delivery formatting, and Pine Script.

Core platform modules:

- `app.platform.models`: users, workspaces, memberships, API keys, settings, and authenticated principals.
- `app.platform.permissions`: centralized permissions and role mappings.
- `app.platform.security`: password hashing, password policy checks, and access token handling.
- `app.platform.authorization`: deny-by-default platform and workspace authorization.
- `app.platform.services`: user login, workspace creation, settings defaults, and bootstrap.
- `app.api.v1`: versioned API routes under `/api/v1`.

Roles:

- `PLATFORM_OWNER`: full platform access.
- `PLATFORM_ADMIN`: platform administration without owner-only control.
- `WORKSPACE_OWNER`: full access inside one workspace.
- `WORKSPACE_ADMIN`: member and API-key administration inside one workspace.
- `TRADER`, `ANALYST`, `VIEWER`: scoped read and operational roles.
- `SERVICE`: service/API-key oriented access.

Platform endpoints:

- `POST /api/v1/auth/login`
- `GET /api/v1/auth/me`
- `GET /api/v1/users`
- `POST /api/v1/users`
- `GET /api/v1/workspaces`
- `POST /api/v1/workspaces`
- `GET /api/v1/workspaces/{workspace_id}/members`
- `POST /api/v1/workspaces/{workspace_id}/api-keys`
- `GET /api/v1/platform/settings`
- `GET /api/v1/system/info`
- `GET /api/v1/system/capabilities`

Authentication:

- User requests use `Authorization: Bearer <token>`.
- Service requests may use `X-API-Key: <key>`.
- API keys are stored as hashes; the raw key is returned only once when created.
- Access tokens are standard PyJWT-signed HS256 tokens with required `exp`, `iat`, `iss`, `aud`, `sub`, and `jti` claims.
- `bcrypt` is required for new password hashes. Legacy PBKDF2 hashes can verify and are upgraded to bcrypt after a successful login.
- Disabled, deleted, unknown, and administratively locked users receive the same generic invalid-credentials login response. Temporary lockout uses the distinct locked-account response until `locked_until` expires.
- When a temporary lockout expires, the account is automatically restored to `ACTIVE`, lock metadata is cleared, failed attempts reset, and the unlock is audited before password verification continues.

Bootstrap:

Set these only for the first platform startup when no users exist:

```bash
PLATFORM_BOOTSTRAP_ENABLED=true
PLATFORM_BOOTSTRAP_EMAIL=owner@example.com
PLATFORM_BOOTSTRAP_PASSWORD=replace-with-a-long-secret
ACCESS_TOKEN_SECRET=replace-with-a-long-random-secret
```

After the first owner is created, disable `PLATFORM_BOOTSTRAP_ENABLED`.

Clean-machine setup:

```bash
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
python -m pytest
uvicorn app.main:app --reload
```

On macOS/Linux, activate with:

```bash
source .venv/bin/activate
```

Production checklist additions:

- Set `ACCESS_TOKEN_SECRET` to a strong private value.
- In production, `ACCESS_TOKEN_SECRET` must be at least 32 bytes for HS256.
- Keep `ACCESS_TOKEN_ALGORITHM=HS256`.
- Configure `PLATFORM_BOOTSTRAP_ENABLED=false` after bootstrap.
- Use restrictive `ALLOWED_HOSTS`.
- Review `/api/v1/system/info` and `/api/v1/system/capabilities` after deployment.

## Phase 18B Personal Operations Mode

Personal Operations Mode turns Queen AI Trader into a one-owner trading operations service. It receives Queen Engine TradingView alerts, validates them, creates and updates trades through the existing Trade State Engine, sends Telegram notifications through the existing durable delivery pipeline, and exposes a protected operations view.

This mode does not add broker execution, copy trading, billing, subscriptions, public registration, or SaaS behavior.

Core settings:

- `PERSONAL_OPERATIONS_MODE=true`
- `TRADINGVIEW_WEBHOOK_SECRET` or `WEBHOOK_SHARED_SECRET`
- `TRADINGVIEW_MAX_SIGNAL_AGE_SECONDS=180`
- `TRADINGVIEW_ALLOWED_SYMBOLS` optional comma-separated allow-list
- `TRADINGVIEW_ALLOWED_TIMEFRAMES` optional comma-separated allow-list
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_DEFAULT_CHAT_ID` or `TELEGRAM_CHAT_IDS`
- `SIGNALS_ENABLED=true`
- `TRADE_UPDATES_ENABLED=true`
- `PAPER_SIGNAL_MODE=PAPER_SIGNAL`

Canonical TradingView event types:

- `SIGNAL_OPEN`
- `TRADE_ACTIVATED`
- `TP_HIT`
- `SL_HIT`
- `TRADE_CLOSED`
- `TRADE_CANCELLED`
- `TRADE_EXPIRED`
- `HEARTBEAT`

Protected operations endpoints:

- `GET /api/v1/operations/status`
- `GET /api/v1/operations/connectivity`
- `GET /api/v1/operations/signals/recent`
- `GET /api/v1/operations/trades/open`
- `GET /api/v1/operations/rejections/recent`
- `GET /api/v1/operations/configuration`
- `POST /api/v1/operations/pause`
- `POST /api/v1/operations/resume`
- `POST /api/v1/operations/test-telegram`

Dashboard:

```text
GET /operations
```

The dashboard is server-rendered HTML, protected by platform authentication, and does not expose secrets.

Personal operations docs:

- `docs/personal-operations.md`
- `docs/webhook-contract.md`
- `docs/tradingview-setup.md`
- `docs/telegram-setup.md`
- `docs/deployment-render.md`
- `docs/operations-runbook.md`

## الحقول الأساسية
- symbol
- timeframe
- side
- entry
- stop_loss
- take_profit_1
- take_profit_2
- take_profit_3
- liquidity_sweep
- mss
- fvg
- order_block
- session
- rr
- secret

## الخطوة التالية
بعد نجاح الـ MVP نضيف:
- تحليل متعدد الفريمات.
- فلتر الأخبار.
- SMT بين الذهب والفضة وDXY.
- لوحة تحكم.
- سجل أداء وإحصاءات.
- Agent لغوي يشرح سبب الصفقة.

## Release Ready Setup

From a clean clone or unzipped repository, run all commands from the repository root.

Create a virtual environment:

```bash
python -m venv .venv
```

Activate it:

```bash
# Windows PowerShell
.\.venv\Scripts\Activate.ps1

# macOS/Linux
source .venv/bin/activate
```

Install dependencies:

```bash
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Validate imports:

```bash
python -c "import app"
python -c "from app.main import app"
```

Run tests:

```bash
pytest
python -m pytest
```

Run the server:

```bash
uvicorn app.main:app --reload
```
