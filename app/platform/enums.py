from enum import Enum


class UserStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    DISABLED = "DISABLED"
    LOCKED = "LOCKED"
    DELETED = "DELETED"


class WorkspaceStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    ARCHIVED = "ARCHIVED"
    DELETED = "DELETED"


class MembershipStatus(str, Enum):
    INVITED = "INVITED"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    REMOVED = "REMOVED"


class ApiKeyStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"
    DISABLED = "DISABLED"


class PlatformRole(str, Enum):
    PLATFORM_OWNER = "PLATFORM_OWNER"
    PLATFORM_ADMIN = "PLATFORM_ADMIN"
    WORKSPACE_OWNER = "WORKSPACE_OWNER"
    WORKSPACE_ADMIN = "WORKSPACE_ADMIN"
    ANALYST = "ANALYST"
    TRADER = "TRADER"
    VIEWER = "VIEWER"
    SERVICE = "SERVICE"


class PrincipalType(str, Enum):
    USER = "USER"
    API_KEY = "API_KEY"
    INTERNAL_SERVICE = "INTERNAL_SERVICE"


class SettingClassification(str, Enum):
    PUBLIC = "PUBLIC"
    INTERNAL = "INTERNAL"
    SECRET = "SECRET"
