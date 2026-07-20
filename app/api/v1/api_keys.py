from fastapi import APIRouter, Depends

from ...platform.api_key_repository import api_key_repository
from ...platform.api_keys import api_key_service
from ...platform.authorization import authorization_service
from ...platform.dependencies import require_authenticated_principal
from ...platform.permissions import API_KEYS_CREATE, API_KEYS_READ, API_KEYS_REVOKE
from ...platform.schemas import ApiKeyCreateRequest, ApiKeyCreateResponse, ApiKeyPublic, envelope

router = APIRouter()


def public(key):
    return ApiKeyPublic.model_validate(key.model_dump()).model_dump(mode="json")


@router.get("/{workspace_id}/api-keys", summary="List workspace API keys")
def list_api_keys(workspace_id: str, principal=Depends(require_authenticated_principal)):
    authorization_service.authorize(principal, API_KEYS_READ, workspace_id)
    return envelope([public(key) for key in api_key_repository.list_by_workspace(workspace_id)])


@router.post("/{workspace_id}/api-keys", summary="Create workspace API key")
def create_api_key(workspace_id: str, payload: ApiKeyCreateRequest, principal=Depends(require_authenticated_principal)):
    authorization_service.authorize(principal, API_KEYS_CREATE, workspace_id)
    key, secret = api_key_service.create_key(workspace_id=workspace_id, owner_user_id=principal.user_id or principal.principal_id, name=payload.name, permissions=payload.permissions, expires_at=payload.expires_at)
    return envelope(ApiKeyCreateResponse(api_key=ApiKeyPublic.model_validate(key.model_dump()), secret=secret).model_dump(mode="json"))


@router.post("/{workspace_id}/api-keys/{api_key_id}/revoke", summary="Revoke workspace API key")
def revoke_api_key(workspace_id: str, api_key_id: str, principal=Depends(require_authenticated_principal)):
    authorization_service.authorize(principal, API_KEYS_REVOKE, workspace_id)
    return envelope(public(api_key_repository.revoke(api_key_id)))
