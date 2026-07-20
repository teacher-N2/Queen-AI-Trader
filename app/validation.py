import json
import time
from typing import Any

from pydantic import ValidationError as PydanticValidationError

from .config import settings
from .errors import ValidationError
from .models import Actionability, Direction, QueenSignalPayload, SignalAction, SignalEvent


class ValidationService:
    def parse_json(self, raw_body: bytes) -> dict[str, Any]:
        try:
            payload = json.loads(raw_body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValidationError("malformed JSON") from exc
        if not isinstance(payload, dict):
            raise ValidationError("webhook payload must be a JSON object")
        return payload

    def validate(self, payload: dict[str, Any]) -> QueenSignalPayload:
        try:
            signal = QueenSignalPayload.model_validate(payload)
        except PydanticValidationError as exc:
            raise ValidationError(str(exc)) from exc

        if signal.schema_version not in settings.allowed_schema_versions:
            raise ValidationError("unsupported schema version")
        if signal.payload_signature_version not in {"shared-secret-v1", "hmac-sha256-v1", "none"}:
            raise ValidationError("unsupported payload signature version")
        if abs(int(time.time() * 1000) - signal.timestamp) > settings.webhook_timestamp_tolerance_seconds * 1000:
            raise ValidationError("timestamp outside tolerance")
        if signal.entry_price is not None and signal.entry_price <= 0:
            raise ValidationError("entry_price must be positive when present")
        if signal.stop_price is not None and signal.stop_price <= 0:
            raise ValidationError("stop_price must be positive when present")
        for target in signal.targets:
            if target.price <= 0:
                raise ValidationError("target prices must be positive")
        self._validate_lifecycle(signal)
        return signal

    def _validate_lifecycle(self, signal: QueenSignalPayload) -> None:
        if signal.actionability == Actionability.ACTIONABLE:
            if signal.event not in {SignalEvent.ENTRY_EXECUTED_SIGNAL, SignalEvent.TRADE_OPENED_SIGNAL}:
                raise ValidationError("only executed entry or opened trade can be actionable")
            if signal.direction not in {Direction.BULLISH, Direction.BEARISH}:
                raise ValidationError("actionable signal requires bullish or bearish direction")
            if signal.action not in {SignalAction.LONG, SignalAction.SHORT}:
                raise ValidationError("actionable signal requires LONG or SHORT action")
            if signal.entry_price is None:
                raise ValidationError("actionable signal requires entry_price")
        if signal.actionability in {Actionability.MANAGEMENT, Actionability.TERMINAL} and not signal.trade_id:
            raise ValidationError("trade lifecycle signal requires trade_id")


validation_service = ValidationService()
