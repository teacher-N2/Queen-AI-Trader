import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta

from ..config import settings
from .api_key_repository import ApiKeyRepository, api_key_repository
from .enums import ApiKeyStatus
from .errors import ApiKeyConflictError, ApiKeyExpiredError, ApiKeyRevokedError, InvalidCredentialsError
from .models import ApiKey


class ApiKeyService:
    def __init__(self, repository: ApiKeyRepository = api_key_repository):
        self.repository = repository

    def create_key(self, *, workspace_id: str, owner_user_id: str, name: str, permissions: list[str], expires_at: str | None = None) -> tuple[ApiKey, str]:
        active_keys = [
            key
            for key in self.repository.list_by_workspace(workspace_id)
            if key.status == ApiKeyStatus.ACTIVE
        ]
        if len(active_keys) >= settings.max_api_keys_per_workspace:
            raise ApiKeyConflictError("workspace api key limit reached")
        raw = "qk_" + secrets.token_urlsafe(32)
        key = ApiKey(
            workspace_id=workspace_id,
            owner_user_id=owner_user_id,
            name=name,
            key_prefix=raw[:12],
            key_hash=self.hash_key(raw),
            permissions=permissions,
            expires_at=expires_at or (datetime.now(UTC) + timedelta(days=settings.api_key_default_expiry_days)).isoformat(),
        )
        return self.repository.create(key), raw

    def hash_key(self, raw_key: str) -> str:
        return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()

    def authenticate(self, raw_key: str) -> ApiKey:
        prefix = raw_key[:12]
        digest = self.hash_key(raw_key)
        for key in self.repository.get_by_prefix(prefix):
            if hmac.compare_digest(key.key_hash, digest):
                if key.status in {ApiKeyStatus.REVOKED, ApiKeyStatus.DISABLED}:
                    raise ApiKeyRevokedError("api key unavailable")
                if key.expires_at and datetime.fromisoformat(key.expires_at) < datetime.now(UTC):
                    raise ApiKeyExpiredError("api key expired")
                self.repository.update_last_used(key.api_key_id)
                return key
        raise InvalidCredentialsError("invalid credentials")


api_key_service = ApiKeyService()
