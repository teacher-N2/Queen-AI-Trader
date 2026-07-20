from dataclasses import dataclass

from .errors import QueenGatewayError


@dataclass(frozen=True)
class ErrorMetadata:
    retryable: bool
    severity: str
    safe_message: str


class ProductionError(QueenGatewayError):
    status_code = 500
    code = "production_error"
    retryable = False
    severity = "error"
    safe_message = "internal service error"

    def metadata(self) -> ErrorMetadata:
        return ErrorMetadata(self.retryable, self.severity, self.safe_message)


class ConfigurationError(ProductionError):
    code = "configuration_error"
    safe_message = "service configuration error"


class DependencyUnavailableError(ProductionError):
    status_code = 503
    code = "dependency_unavailable"
    retryable = True
    safe_message = "temporary dependency unavailable"


class PersistenceError(ProductionError):
    code = "persistence_error"
    safe_message = "persistent storage error"


class RecoveryError(ProductionError):
    code = "recovery_error"
    safe_message = "service recovery error"


class IdempotencyConflictError(ProductionError):
    status_code = 409
    code = "idempotency_conflict"
    safe_message = "conflicting idempotency key"


class CircuitBreakerOpenError(DependencyUnavailableError):
    code = "circuit_breaker_open"
    safe_message = "dependency circuit breaker is open"


class RetryExhaustedError(DependencyUnavailableError):
    code = "retry_exhausted"
    safe_message = "retry attempts exhausted"


class ConcurrencyConflictError(ProductionError):
    status_code = 409
    code = "concurrency_conflict"
    safe_message = "concurrent update conflict"


class DeadLetterError(ProductionError):
    code = "dead_letter_error"
    safe_message = "dead letter handling error"


class ReadinessError(ProductionError):
    status_code = 503
    code = "readiness_error"
    safe_message = "service is not ready"


class TimeoutOperationError(DependencyUnavailableError):
    code = "operation_timeout"
    safe_message = "operation timed out"
