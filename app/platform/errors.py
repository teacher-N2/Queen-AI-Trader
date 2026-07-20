from ..production_errors import ProductionError


class PlatformError(ProductionError):
    code = "platform_error"


class UserNotFoundError(PlatformError):
    status_code = 404
    code = "user_not_found"


class UserAlreadyExistsError(PlatformError):
    status_code = 409
    code = "user_already_exists"


class UserDisabledError(PlatformError):
    status_code = 403
    code = "user_disabled"


class InvalidCredentialsError(PlatformError):
    status_code = 401
    code = "invalid_credentials"
    safe_message = "invalid credentials"


class AccountLockedError(PlatformError):
    status_code = 423
    code = "account_locked"


class WorkspaceNotFoundError(PlatformError):
    status_code = 404
    code = "workspace_not_found"


class WorkspaceAlreadyExistsError(PlatformError):
    status_code = 409
    code = "workspace_already_exists"


class WorkspaceAccessDeniedError(PlatformError):
    status_code = 403
    code = "workspace_access_denied"


class FinalWorkspaceOwnerError(PlatformError):
    status_code = 409
    code = "final_workspace_owner"


class MembershipNotFoundError(PlatformError):
    status_code = 404
    code = "membership_not_found"


class MembershipConflictError(PlatformError):
    status_code = 409
    code = "membership_conflict"


class PermissionDeniedError(PlatformError):
    status_code = 403
    code = "permission_denied"


class ApiKeyNotFoundError(PlatformError):
    status_code = 404
    code = "api_key_not_found"


class ApiKeyRevokedError(PlatformError):
    status_code = 403
    code = "api_key_revoked"


class ApiKeyExpiredError(PlatformError):
    status_code = 403
    code = "api_key_expired"


class ApiKeyConflictError(PlatformError):
    status_code = 409
    code = "api_key_conflict"


class PlatformSettingError(PlatformError):
    status_code = 422
    code = "platform_setting_error"


class BootstrapError(PlatformError):
    status_code = 409
    code = "bootstrap_error"
