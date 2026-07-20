from fastapi import APIRouter, Depends

from ...platform.dependencies import require_platform_permission
from ...platform.permissions import USERS_CREATE, USERS_DISABLE, USERS_READ, USERS_UPDATE
from ...platform.schemas import PageParams, UserCreateRequest, UserPatchRequest, UserPublic, envelope
from ...platform.services import user_service
from ...platform.user_repository import user_repository

router = APIRouter()


def public(user):
    return UserPublic.model_validate(user.model_dump()).model_dump(mode="json")


@router.get("", summary="List users")
def list_users(params: PageParams = Depends(), principal=Depends(require_platform_permission(USERS_READ))):
    return envelope([public(user) for user in user_repository.list(limit=params.limit, offset=params.offset)])


@router.post("", summary="Create user")
def create_user(payload: UserCreateRequest, principal=Depends(require_platform_permission(USERS_CREATE))):
    user = user_service.create_user(email=payload.email, display_name=payload.display_name, password=payload.password, platform_roles=payload.platform_roles)
    return envelope(public(user))


@router.get("/{user_id}", summary="Get user")
def get_user(user_id: str, principal=Depends(require_platform_permission(USERS_READ))):
    return envelope(public(user_repository.get_by_id(user_id)))


@router.patch("/{user_id}", summary="Update user")
def update_user(user_id: str, payload: UserPatchRequest, principal=Depends(require_platform_permission(USERS_UPDATE))):
    user = user_repository.get_by_id(user_id)
    if payload.display_name is not None:
        user.display_name = payload.display_name
    if payload.status is not None:
        user.status = payload.status
    return envelope(public(user_repository.update(user)))


@router.post("/{user_id}/disable", summary="Disable user")
def disable_user(user_id: str, principal=Depends(require_platform_permission(USERS_DISABLE))):
    return envelope(public(user_repository.disable(user_id)))


@router.post("/{user_id}/enable", summary="Enable user")
def enable_user(user_id: str, principal=Depends(require_platform_permission(USERS_UPDATE))):
    user = user_repository.get_by_id(user_id)
    from ...platform.enums import UserStatus

    user.status = UserStatus.ACTIVE
    return envelope(public(user_repository.update(user)))
