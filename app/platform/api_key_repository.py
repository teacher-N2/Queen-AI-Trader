from datetime import UTC, datetime

from .enums import ApiKeyStatus
from .errors import ApiKeyNotFoundError
from .models import ApiKey
from .repository import JsonRepository


class ApiKeyRepository:
    def __init__(self, repo: JsonRepository[ApiKey] | None = None):
        self.repo = repo or JsonRepository("api_keys.json", ApiKey)

    def create(self, api_key: ApiKey) -> ApiKey:
        keys = self.repo.all()
        keys.append(api_key)
        self.repo.replace_all(keys)
        return api_key

    def get_by_id(self, api_key_id: str) -> ApiKey:
        for key in self.repo.all():
            if key.api_key_id == api_key_id:
                return key
        raise ApiKeyNotFoundError("api key not found")

    def get_by_prefix(self, key_prefix: str) -> list[ApiKey]:
        return [key for key in self.repo.all() if key.key_prefix == key_prefix]

    def list_by_workspace(self, workspace_id: str) -> list[ApiKey]:
        return [key for key in self.repo.all() if key.workspace_id == workspace_id]

    def revoke(self, api_key_id: str) -> ApiKey:
        key = self.get_by_id(api_key_id)
        key.status = ApiKeyStatus.REVOKED
        key.revoked_at = datetime.now(UTC).isoformat()
        self._update(key)
        return key

    def update_last_used(self, api_key_id: str) -> None:
        key = self.get_by_id(api_key_id)
        key.last_used_at = datetime.now(UTC).isoformat()
        self._update(key)

    def _update(self, api_key: ApiKey) -> None:
        keys = self.repo.all()
        for index, existing in enumerate(keys):
            if existing.api_key_id == api_key.api_key_id:
                keys[index] = api_key
                self.repo.replace_all(keys)
                return
        raise ApiKeyNotFoundError("api key not found")


api_key_repository = ApiKeyRepository()
