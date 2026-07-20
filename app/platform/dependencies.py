from fastapi import Depends, Header

from .api_keys import api_key_service
from .authorization import authorization_service
from .errors import InvalidCredentialsError, PermissionDeniedError
from .models import Principal
from .permissions import PLATFORM_MANAGE
from .security import token_service
from .user_repository import user_repository


async def require_authenticated_principal(
    authorization: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> Principal:
    if x_api_key:
        api_key = api_key_service.authenticate(x_api_key)
        return authorization_service.principal_for_api_key(api_key)
    if not authorization or not authorization.lower().startswith("bearer "):
        raise InvalidCredentialsError("invalid credentials")
    claims = token_service.verify_access_token(authorization.split(" ", 1)[1])
    user = user_repository.get_by_id(str(claims["sub"]))
    return authorization_service.principal_for_user(user)


def require_platform_permission(permission: str):
    async def dependency(principal: Principal = Depends(require_authenticated_principal)) -> Principal:
        authorization_service.authorize(principal, permission)
        return principal

    return dependency


def require_workspace_permission(permission: str, workspace_id: str):
    async def dependency(principal: Principal = Depends(require_authenticated_principal)) -> Principal:
        authorization_service.authorize(principal, permission, workspace_id)
        return principal

    return dependency


async def require_platform_admin(principal: Principal = Depends(require_authenticated_principal)) -> Principal:
    try:
        authorization_service.authorize(principal, PLATFORM_MANAGE)
    except PermissionDeniedError:
        raise
    return principal
