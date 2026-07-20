class QueenGatewayError(Exception):
    status_code = 400
    code = "gateway_error"

    def __init__(self, message: str, *, code: str | None = None):
        super().__init__(message)
        if code:
            self.code = code
        self.message = message


class ValidationError(QueenGatewayError):
    status_code = 422
    code = "validation_error"


class AuthenticationError(QueenGatewayError):
    status_code = 401
    code = "authentication_error"


class ReplayError(QueenGatewayError):
    status_code = 409
    code = "replay_error"


class DeliveryError(QueenGatewayError):
    status_code = 502
    code = "delivery_error"


class RetryExceededError(DeliveryError):
    code = "retry_exceeded"


class ConfigurationError(QueenGatewayError):
    status_code = 500
    code = "configuration_error"
