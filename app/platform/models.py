from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

from .enums import ApiKeyStatus, MembershipStatus, PlatformRole, PrincipalType, SettingClassification, UserStatus, WorkspaceStatus


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def opaque_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


class User(BaseModel):
    user_id: str = Field(default_factory=lambda: opaque_id("usr"))
    email: str
    normalized_email: str
    display_name: str
    password_hash: str
    status: UserStatus = UserStatus.PENDING
    is_platform_admin: bool = False
    platform_roles: list[PlatformRole] = Field(default_factory=list)
    failed_login_attempts: int = 0
    locked_until: str | None = None
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)
    last_login_at: str | None = None
    disabled_at: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    version: int = 1


class Workspace(BaseModel):
    workspace_id: str = Field(default_factory=lambda: opaque_id("wks"))
    name: str
    slug: str
    status: WorkspaceStatus = WorkspaceStatus.ACTIVE
    created_by_user_id: str
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)
    disabled_at: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    version: int = 1


class WorkspaceMembership(BaseModel):
    membership_id: str = Field(default_factory=lambda: opaque_id("mem"))
    workspace_id: str
    user_id: str
    role: PlatformRole
    status: MembershipStatus = MembershipStatus.ACTIVE
    invited_by_user_id: str | None = None
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)
    disabled_at: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ApiKey(BaseModel):
    api_key_id: str = Field(default_factory=lambda: opaque_id("key"))
    workspace_id: str
    owner_user_id: str
    name: str
    key_prefix: str
    key_hash: str
    status: ApiKeyStatus = ApiKeyStatus.ACTIVE
    permissions: list[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=now_iso)
    last_used_at: str | None = None
    expires_at: str | None = None
    revoked_at: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class PlatformSetting(BaseModel):
    setting_id: str = Field(default_factory=lambda: opaque_id("set"))
    key: str
    value: Any
    classification: SettingClassification = SettingClassification.INTERNAL
    updated_at: str = Field(default_factory=now_iso)
    updated_by: str | None = None
    version: int = 1


class Principal(BaseModel):
    principal_id: str
    principal_type: PrincipalType
    user_id: str | None = None
    api_key_id: str | None = None
    workspace_id: str | None = None
    roles: list[PlatformRole] = Field(default_factory=list)
    permissions: list[str] = Field(default_factory=list)
    authenticated_at: str = Field(default_factory=now_iso)
    metadata: dict[str, Any] = Field(default_factory=dict)
