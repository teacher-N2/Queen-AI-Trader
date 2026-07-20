from fastapi import APIRouter, Depends

from ...platform.dependencies import require_platform_permission
from ...platform.permissions import PLATFORM_SETTINGS_MANAGE, PLATFORM_SETTINGS_READ
from ...platform.schemas import SettingPatchRequest, SettingPublic, envelope
from ...platform.services import platform_settings_service

router = APIRouter()


def public(setting):
    return SettingPublic(key=setting.key, value=setting.value, classification=setting.classification.value, updated_at=setting.updated_at).model_dump()


@router.get("", summary="List platform settings")
def list_settings(principal=Depends(require_platform_permission(PLATFORM_SETTINGS_READ))):
    return envelope([public(setting) for setting in platform_settings_service.list_safe()])


@router.patch("/{key}", summary="Update platform setting")
def update_setting(key: str, payload: SettingPatchRequest, principal=Depends(require_platform_permission(PLATFORM_SETTINGS_MANAGE))):
    return envelope(public(platform_settings_service.set(key, payload.value, actor=principal.principal_id)))
