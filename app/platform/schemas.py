from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

from ..runtime_context import get_context
from .enums import ApiKeyStatus, MembershipStatus, PlatformRole, UserStatus, WorkspaceStatus


class ApiMeta(BaseModel):
    request_id: str
    correlation_id: str
    timestamp: str
    api_version: str = "v1"


class ApiResponse(BaseModel):
    data: Any
    meta: ApiMeta


class ApiErrorBody(BaseModel):
    code: str
    message: str
    retryable: bool = False
    details: Any = None


class ApiErrorResponse(BaseModel):
    error: ApiErrorBody
    meta: ApiMeta


def envelope(data: Any) -> dict[str, Any]:
    context = get_context()
    return {
        "data": data,
        "meta": {
            "request_id": context.request_id,
            "correlation_id": context.correlation_id,
            "timestamp": datetime.now(UTC).isoformat(),
            "api_version": "v1",
        },
    }


class LoginRequest(BaseModel):
    email: str
    password: str = Field(min_length=1)


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in_minutes: int


class UserCreateRequest(BaseModel):
    email: str
    display_name: str
    password: str
    platform_roles: list[PlatformRole] = Field(default_factory=list)


class UserPatchRequest(BaseModel):
    display_name: str | None = None
    status: UserStatus | None = None


class UserPublic(BaseModel):
    user_id: str
    email: str
    display_name: str
    status: UserStatus
    is_platform_admin: bool
    platform_roles: list[PlatformRole]
    created_at: str
    updated_at: str
    last_login_at: str | None = None


class WorkspaceCreateRequest(BaseModel):
    name: str
    slug: str | None = None


class WorkspacePatchRequest(BaseModel):
    name: str | None = None
    status: WorkspaceStatus | None = None


class WorkspacePublic(BaseModel):
    workspace_id: str
    name: str
    slug: str
    status: WorkspaceStatus
    created_by_user_id: str
    created_at: str
    updated_at: str


class MembershipCreateRequest(BaseModel):
    user_id: str
    role: PlatformRole


class MembershipPatchRequest(BaseModel):
    role: PlatformRole | None = None
    status: MembershipStatus | None = None


class MembershipPublic(BaseModel):
    membership_id: str
    workspace_id: str
    user_id: str
    role: PlatformRole
    status: MembershipStatus


class ApiKeyCreateRequest(BaseModel):
    name: str
    permissions: list[str] = Field(default_factory=list)
    expires_at: str | None = None


class ApiKeyPublic(BaseModel):
    api_key_id: str
    workspace_id: str
    owner_user_id: str
    name: str
    key_prefix: str
    status: ApiKeyStatus
    permissions: list[str]
    created_at: str
    last_used_at: str | None = None
    expires_at: str | None = None


class ApiKeyCreateResponse(BaseModel):
    api_key: ApiKeyPublic
    secret: str


class SettingPatchRequest(BaseModel):
    value: Any


class SettingPublic(BaseModel):
    key: str
    value: Any
    classification: str
    updated_at: str


class PageParams(BaseModel):
    limit: int = Field(default=50, ge=1, le=100)
    offset: int = Field(default=0, ge=0)
