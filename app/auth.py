import hmac
import json
import time
from hashlib import sha256

from fastapi import Request

from .config import settings
from .errors import AuthenticationError, ConfigurationError


class AuthenticationService:
    def authenticate(self, request: Request, raw_body: bytes) -> None:
        if not settings.webhook_shared_secret:
            raise ConfigurationError("webhook shared secret is not configured")

        provided_secret = request.headers.get(settings.webhook_secret_header, "")
        if not provided_secret:
            provided_secret = self._payload_secret(raw_body)
        if provided_secret:
            if not hmac.compare_digest(provided_secret, settings.webhook_shared_secret):
                raise AuthenticationError("invalid webhook shared secret")
        elif not settings.require_signature:
            raise AuthenticationError("missing webhook shared secret")

        signature = request.headers.get(settings.webhook_signature_header, "")
        timestamp = request.headers.get(settings.webhook_timestamp_header, "")
        if settings.require_signature or signature:
            self._validate_signature(signature, timestamp, raw_body)

    def _validate_signature(self, signature: str, timestamp: str, raw_body: bytes) -> None:
        if not settings.webhook_signature_secret:
            raise ConfigurationError("webhook signature secret is not configured")
        if not signature or not timestamp:
            raise AuthenticationError("missing webhook signature headers")
        try:
            timestamp_seconds = int(timestamp)
        except ValueError as exc:
            raise AuthenticationError("invalid webhook timestamp header") from exc
        if abs(int(time.time()) - timestamp_seconds) > settings.webhook_timestamp_tolerance_seconds:
            raise AuthenticationError("webhook signature timestamp outside tolerance")

        signed_body = timestamp.encode("utf-8") + b"." + raw_body
        expected = hmac.new(settings.webhook_signature_secret.encode("utf-8"), signed_body, sha256).hexdigest()
        normalized = signature.removeprefix("sha256=")
        if not hmac.compare_digest(normalized, expected):
            raise AuthenticationError("invalid webhook signature")

    def _payload_secret(self, raw_body: bytes) -> str:
        try:
            payload = json.loads(raw_body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return ""
        if not isinstance(payload, dict):
            return ""
        return str(payload.get("secret") or payload.get("webhook_secret") or "")


auth_service = AuthenticationService()
