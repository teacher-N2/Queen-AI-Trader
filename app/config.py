import os
from dataclasses import dataclass
from pathlib import Path

try:
    from dotenv import load_dotenv
except ModuleNotFoundError:
    def load_dotenv() -> None:
        return None

load_dotenv()


def _int_env(name: str, default: int) -> int:
    raw_value = os.getenv(name)
    if raw_value is None or raw_value == "":
        return default
    return int(raw_value)


def _float_env(name: str, default: float) -> float:
    raw_value = os.getenv(name)
    if raw_value is None or raw_value == "":
        return default
    return float(raw_value)


def _csv_env(name: str, fallback: str = "") -> list[str]:
    raw_value = os.getenv(name, fallback)
    return [item.strip() for item in raw_value.split(",") if item.strip()]


def _bool_env(name: str, default: bool = False) -> bool:
    raw_value = os.getenv(name)
    if raw_value is None or raw_value == "":
        return default
    return raw_value.lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    app_name: str = os.getenv("APP_NAME", "Queen AI Trader")
    app_version: str = os.getenv("APP_VERSION", "0.18.0")
    environment: str = os.getenv("ENVIRONMENT", "development")
    debug: bool = _bool_env("DEBUG", False)
    log_level: str = os.getenv("LOG_LEVEL", "INFO")
    log_format: str = os.getenv("LOG_FORMAT", "json")

    webhook_shared_secret: str = os.getenv(
        "WEBHOOK_SHARED_SECRET",
        os.getenv("TRADINGVIEW_WEBHOOK_SECRET", ""),
    )
    webhook_signature_secret: str = os.getenv("WEBHOOK_SIGNATURE_SECRET", "")
    webhook_signature_header: str = os.getenv("WEBHOOK_SIGNATURE_HEADER", "x-queen-signature")
    webhook_secret_header: str = os.getenv("WEBHOOK_SECRET_HEADER", "x-queen-secret")
    webhook_timestamp_header: str = os.getenv("WEBHOOK_TIMESTAMP_HEADER", "x-queen-timestamp")
    webhook_timestamp_tolerance_seconds: int = _int_env("WEBHOOK_TIMESTAMP_TOLERANCE_SECONDS", 300)
    allowed_schema_versions: tuple[str, ...] = tuple(_csv_env("ALLOWED_SCHEMA_VERSIONS", "1.0"))
    require_signature: bool = _bool_env("REQUIRE_WEBHOOK_SIGNATURE", False)
    max_request_body_bytes: int = _int_env("MAX_REQUEST_BODY_BYTES", 262144)
    allowed_hosts: tuple[str, ...] = tuple(_csv_env("ALLOWED_HOSTS", "*"))
    cors_origins: tuple[str, ...] = tuple(_csv_env("CORS_ORIGINS", ""))

    telegram_bot_token: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    telegram_chat_ids: tuple[str, ...] = tuple(_csv_env("TELEGRAM_CHAT_IDS", os.getenv("TELEGRAM_CHAT_ID", "")))
    telegram_default_chat_id: str = os.getenv("TELEGRAM_DEFAULT_CHAT_ID", os.getenv("TELEGRAM_CHAT_ID", ""))
    telegram_scalp_chat_id: str = os.getenv("TELEGRAM_SCALP_CHAT_ID", "")
    telegram_intraday_chat_id: str = os.getenv("TELEGRAM_INTRADAY_CHAT_ID", "")
    telegram_swing_chat_id: str = os.getenv("TELEGRAM_SWING_CHAT_ID", "")
    telegram_error_chat_id: str = os.getenv("TELEGRAM_ERROR_CHAT_ID", "")
    telegram_parse_mode: str = os.getenv("TELEGRAM_PARSE_MODE", "Markdown")
    telegram_enabled: bool = _bool_env("TELEGRAM_ENABLED", True)

    storage_dir: Path = Path(os.getenv("STORAGE_DIR", "data"))
    processed_signals_file: str = os.getenv("PROCESSED_SIGNALS_FILE", "processed_signals.jsonl")
    delivery_history_file: str = os.getenv("DELIVERY_HISTORY_FILE", "delivery_history.jsonl")
    audit_log_file: str = os.getenv("AUDIT_LOG_FILE", "audit_log.jsonl")
    dead_letter_file: str = os.getenv("DEAD_LETTER_FILE", "dead_letters.jsonl")
    trade_snapshot_file: str = os.getenv("TRADE_SNAPSHOT_FILE", "trade_snapshots.jsonl")
    trade_history_file: str = os.getenv("TRADE_HISTORY_FILE", "trade_history.jsonl")

    delivery_max_attempts: int = _int_env("DELIVERY_MAX_ATTEMPTS", 3)
    delivery_initial_backoff_seconds: float = _float_env("DELIVERY_INITIAL_BACKOFF_SECONDS", 0.5)
    delivery_max_backoff_seconds: float = _float_env("DELIVERY_MAX_BACKOFF_SECONDS", 5.0)
    request_timeout_seconds: float = _float_env("REQUEST_TIMEOUT_SECONDS", 15.0)
    shutdown_drain_timeout_seconds: float = _float_env("SHUTDOWN_DRAIN_TIMEOUT_SECONDS", 10.0)

    retry_jitter_seconds: float = _float_env("RETRY_JITTER_SECONDS", 0.1)
    retry_overall_timeout_seconds: float = _float_env("RETRY_OVERALL_TIMEOUT_SECONDS", 30.0)
    webhook_operation_lease_seconds: int = _int_env("WEBHOOK_OPERATION_LEASE_SECONDS", 120)
    delivery_operation_lease_seconds: int = _int_env("DELIVERY_OPERATION_LEASE_SECONDS", 120)
    delivery_recovery_limit: int = _int_env("DELIVERY_RECOVERY_LIMIT", 25)
    allow_unsafe_wildcard_hosts: bool = _bool_env("ALLOW_UNSAFE_WILDCARD_HOSTS", False)

    circuit_failure_threshold: int = _int_env("CIRCUIT_FAILURE_THRESHOLD", 5)
    circuit_recovery_timeout_seconds: float = _float_env("CIRCUIT_RECOVERY_TIMEOUT_SECONDS", 30.0)
    circuit_half_open_probe_limit: int = _int_env("CIRCUIT_HALF_OPEN_PROBE_LIMIT", 1)
    circuit_success_threshold: int = _int_env("CIRCUIT_SUCCESS_THRESHOLD", 1)

    idempotency_records_file: str = os.getenv("IDEMPOTENCY_RECORDS_FILE", "idempotency_records.jsonl")
    idempotency_retention_seconds: int = _int_env("IDEMPOTENCY_RETENTION_SECONDS", 604800)

    dead_letter_retention_seconds: int = _int_env("DEAD_LETTER_RETENTION_SECONDS", 2592000)

    platform_enabled: bool = _bool_env("PLATFORM_ENABLED", True)
    platform_name: str = os.getenv("PLATFORM_NAME", "Queen Platform")
    platform_bootstrap_enabled: bool = _bool_env("PLATFORM_BOOTSTRAP_ENABLED", False)
    platform_bootstrap_email: str = os.getenv("PLATFORM_BOOTSTRAP_EMAIL", "")
    platform_bootstrap_password: str = os.getenv("PLATFORM_BOOTSTRAP_PASSWORD", "")
    access_token_secret: str = os.getenv("ACCESS_TOKEN_SECRET", os.getenv("WEBHOOK_SHARED_SECRET", "dev-access-token-secret-change-me-32-bytes-minimum"))
    access_token_algorithm: str = os.getenv("ACCESS_TOKEN_ALGORITHM", "HS256")
    access_token_expire_minutes: int = _int_env("ACCESS_TOKEN_EXPIRE_MINUTES", 30)
    access_token_iat_leeway_seconds: int = _int_env("ACCESS_TOKEN_IAT_LEEWAY_SECONDS", 30)
    access_token_issuer: str = os.getenv("ACCESS_TOKEN_ISSUER", "queen-ai-trader")
    access_token_audience: str = os.getenv("ACCESS_TOKEN_AUDIENCE", "queen-platform")
    password_min_length: int = _int_env("PASSWORD_MIN_LENGTH", 12)
    password_max_length: int = _int_env("PASSWORD_MAX_LENGTH", 128)
    password_require_uppercase: bool = _bool_env("PASSWORD_REQUIRE_UPPERCASE", False)
    password_require_lowercase: bool = _bool_env("PASSWORD_REQUIRE_LOWERCASE", False)
    password_require_numeric: bool = _bool_env("PASSWORD_REQUIRE_NUMERIC", False)
    password_require_special: bool = _bool_env("PASSWORD_REQUIRE_SPECIAL", False)
    login_max_failures: int = _int_env("LOGIN_MAX_FAILURES", 5)
    login_lockout_minutes: int = _int_env("LOGIN_LOCKOUT_MINUTES", 15)
    api_key_default_expiry_days: int = _int_env("API_KEY_DEFAULT_EXPIRY_DAYS", 365)
    max_api_keys_per_workspace: int = _int_env("MAX_API_KEYS_PER_WORKSPACE", 20)
    maximum_workspaces_per_user: int = _int_env("MAXIMUM_WORKSPACES_PER_USER", 25)
    default_timezone: str = os.getenv("DEFAULT_TIMEZONE", "UTC")
    default_locale: str = os.getenv("DEFAULT_LOCALE", "en")
    legacy_workspace_slug: str = os.getenv("LEGACY_WORKSPACE_SLUG", "legacy")

    personal_operations_mode: bool = _bool_env("PERSONAL_OPERATIONS_MODE", False)
    personal_owner_user_id: str = os.getenv("PERSONAL_OWNER_USER_ID", "")
    personal_workspace_id: str = os.getenv("PERSONAL_WORKSPACE_ID", "")
    tradingview_max_signal_age_seconds: int = _int_env("TRADINGVIEW_MAX_SIGNAL_AGE_SECONDS", 180)
    tradingview_warn_signal_age_seconds: int = _int_env("TRADINGVIEW_WARN_SIGNAL_AGE_SECONDS", 60)
    tradingview_future_tolerance_seconds: int = _int_env("TRADINGVIEW_FUTURE_TOLERANCE_SECONDS", 30)
    tradingview_allowed_symbols: tuple[str, ...] = tuple(_csv_env("TRADINGVIEW_ALLOWED_SYMBOLS", ""))
    tradingview_allowed_timeframes: tuple[str, ...] = tuple(_csv_env("TRADINGVIEW_ALLOWED_TIMEFRAMES", ""))
    tradingview_allowed_event_types: tuple[str, ...] = tuple(_csv_env("TRADINGVIEW_ALLOWED_EVENT_TYPES", "SIGNAL_OPEN,TRADE_ACTIVATED,TP_HIT,SL_HIT,TRADE_CLOSED,TRADE_CANCELLED,TRADE_EXPIRED,HEARTBEAT"))
    signals_enabled: bool = _bool_env("SIGNALS_ENABLED", True)
    trade_updates_enabled: bool = _bool_env("TRADE_UPDATES_ENABLED", True)
    paper_signal_mode: str = os.getenv("PAPER_SIGNAL_MODE", "PAPER_SIGNAL")
    operations_dashboard_enabled: bool = _bool_env("OPERATIONS_DASHBOARD_ENABLED", True)
    operations_history_limit: int = _int_env("OPERATIONS_HISTORY_LIMIT", 100)
    stale_connection_seconds: int = _int_env("STALE_CONNECTION_SECONDS", 600)
    signal_age_policy: str = os.getenv("SIGNAL_AGE_POLICY", "REJECT")
    signal_min_confidence: int = _int_env("SIGNAL_MIN_CONFIDENCE", 0)
    max_take_profit_count: int = _int_env("MAX_TAKE_PROFIT_COUNT", 5)
    max_metadata_fields: int = _int_env("MAX_METADATA_FIELDS", 25)
    default_entry_deviation_percent: float = _float_env("DEFAULT_ENTRY_DEVIATION_PERCENT", 0.5)
    gold_entry_deviation_percent: float = _float_env("GOLD_ENTRY_DEVIATION_PERCENT", 0.15)
    nasdaq_entry_deviation_percent: float = _float_env("NASDAQ_ENTRY_DEVIATION_PERCENT", 0.25)
    forex_entry_deviation_percent: float = _float_env("FOREX_ENTRY_DEVIATION_PERCENT", 0.05)
    crypto_entry_deviation_percent: float = _float_env("CRYPTO_ENTRY_DEVIATION_PERCENT", 0.5)
    webhook_rate_limit_per_minute: int = _int_env("WEBHOOK_RATE_LIMIT_PER_MINUTE", 120)
    login_rate_limit_per_minute: int = _int_env("LOGIN_RATE_LIMIT_PER_MINUTE", 20)
    telegram_test_rate_limit_per_minute: int = _int_env("TELEGRAM_TEST_RATE_LIMIT_PER_MINUTE", 3)
    operations_action_rate_limit_per_minute: int = _int_env("OPERATIONS_ACTION_RATE_LIMIT_PER_MINUTE", 10)

    def validate_startup(self) -> None:
        from .production_errors import ConfigurationError

        if self.environment == "production":
            if not self.webhook_shared_secret:
                raise ConfigurationError("WEBHOOK_SHARED_SECRET is required in production")
            if self.debug:
                raise ConfigurationError("DEBUG must be false in production")
            if "*" in self.allowed_hosts and not self.allow_unsafe_wildcard_hosts:
                raise ConfigurationError("wildcard ALLOWED_HOSTS is unsafe in production")
            if self.telegram_enabled and (not self.telegram_bot_token or not self.telegram_chat_ids):
                raise ConfigurationError("Telegram token and chat IDs are required when Telegram is enabled")
        if self.delivery_max_attempts < 1:
            raise ConfigurationError("DELIVERY_MAX_ATTEMPTS must be at least 1")
        if self.request_timeout_seconds <= 0 or self.retry_overall_timeout_seconds <= 0:
            raise ConfigurationError("timeout values must be positive")
        if self.idempotency_retention_seconds <= 0 or self.dead_letter_retention_seconds <= 0:
            raise ConfigurationError("retention values must be positive")
        if self.max_request_body_bytes <= 0:
            raise ConfigurationError("MAX_REQUEST_BODY_BYTES must be positive")
        if self.circuit_failure_threshold < 1 or self.circuit_half_open_probe_limit < 1 or self.circuit_success_threshold < 1:
            raise ConfigurationError("circuit breaker thresholds must be positive")
        if self.platform_enabled:
            if self.access_token_algorithm not in {"HS256"}:
                raise ConfigurationError("unsupported ACCESS_TOKEN_ALGORITHM")
            if self.environment == "production":
                if self.access_token_secret in {"", "dev-access-token-secret", "dev-access-token-secret-change-me-32-bytes-minimum"}:
                    raise ConfigurationError("ACCESS_TOKEN_SECRET is required in production")
                if len(self.access_token_secret.encode("utf-8")) < 32:
                    raise ConfigurationError("ACCESS_TOKEN_SECRET must be at least 32 bytes in production")
            if self.password_min_length < 8 or self.password_max_length < self.password_min_length:
                raise ConfigurationError("invalid password policy")
            if self.login_max_failures < 1 or self.login_lockout_minutes < 1:
                raise ConfigurationError("invalid login lockout policy")
        if self.personal_operations_mode:
            if self.tradingview_max_signal_age_seconds <= 0 or self.tradingview_warn_signal_age_seconds < 0:
                raise ConfigurationError("invalid TradingView signal age policy")
            if self.tradingview_future_tolerance_seconds < 0:
                raise ConfigurationError("invalid TradingView future timestamp tolerance")
            if self.signal_age_policy not in {"ACCEPT", "WARN", "REJECT"}:
                raise ConfigurationError("invalid SIGNAL_AGE_POLICY")
            if self.paper_signal_mode not in {"DISABLED", "PAPER_SIGNAL", "LIVE_SIGNAL"}:
                raise ConfigurationError("invalid PAPER_SIGNAL_MODE")
            if self.max_take_profit_count < 1:
                raise ConfigurationError("MAX_TAKE_PROFIT_COUNT must be positive")
            if self.environment == "production" and not self.webhook_shared_secret:
                raise ConfigurationError("TRADINGVIEW_WEBHOOK_SECRET is required in production personal operations mode")
            destinations = [self.telegram_default_chat_id, *self.telegram_chat_ids]
            if self.telegram_enabled and self.signals_enabled and not any(destinations):
                raise ConfigurationError("at least one Telegram destination is required when personal signal delivery is enabled")


settings = Settings()

# Backward-compatible names for legacy modules that are no longer used by the Phase 14 gateway path.
TRADINGVIEW_WEBHOOK_SECRET = settings.webhook_shared_secret
TELEGRAM_BOT_TOKEN = settings.telegram_bot_token
TELEGRAM_CHAT_ID = settings.telegram_chat_ids[0] if settings.telegram_chat_ids else ""
MIN_QUEEN_SCORE = _int_env("MIN_QUEEN_SCORE", 80)
MAX_TRADES_PER_DAY = _int_env("MAX_TRADES_PER_DAY", 7)
MAX_DAILY_LOSSES = _int_env("MAX_DAILY_LOSSES", 3)
MAX_RISK_PERCENT_PER_TRADE = _float_env("MAX_RISK_PERCENT_PER_TRADE", 0.5)
