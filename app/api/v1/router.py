from fastapi import APIRouter

from . import auth, users, workspaces, memberships, api_keys, platform_settings, system, operations

router = APIRouter(prefix="/api/v1")
router.include_router(auth.router, prefix="/auth", tags=["auth"])
router.include_router(users.router, prefix="/users", tags=["users"])
router.include_router(workspaces.router, prefix="/workspaces", tags=["workspaces"])
router.include_router(memberships.router, prefix="/workspaces", tags=["memberships"])
router.include_router(api_keys.router, prefix="/workspaces", tags=["api_keys"])
router.include_router(platform_settings.router, prefix="/platform/settings", tags=["platform_settings"])
router.include_router(system.router, prefix="/system", tags=["system"])
router.include_router(operations.router, prefix="/operations", tags=["operations"])
