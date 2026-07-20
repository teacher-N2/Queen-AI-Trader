from fastapi import APIRouter

from ...config import settings
from ...metrics import metrics
from ...platform.schemas import envelope
from ...platform.settings_repository import settings_repository
from ...telegram import telegram_service

router = APIRouter()


@router.get("/info", summary="Safe system information")
def info():
    maintenance = settings_repository.get("maintenance_mode")
    return envelope(
        {
            "application_name": settings.app_name,
            "application_version": settings.app_version,
            "api_version": "v1",
            "environment": settings.environment,
            "platform_name": settings.platform_name,
            "maintenance_mode": bool(maintenance.value) if maintenance else False,
            "uptime": metrics.snapshot().get("uptime_seconds"),
        }
    )


@router.get("/capabilities", summary="Safe platform capabilities")
def capabilities():
    return envelope(
        {
            "users_enabled": True,
            "workspaces_enabled": True,
            "api_keys_enabled": True,
            "analytics_available": True,
            "telegram_enabled": telegram_service.configured(),
            "recovery_enabled": True,
            "metrics_enabled": True,
        }
    )
