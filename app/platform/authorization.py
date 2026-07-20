from datetime import UTC, datetime

from .audit import platform_audit
from .enums import ApiKeyStatus, MembershipStatus, PlatformRole, PrincipalType, UserStatus
from .errors import PermissionDeniedError
from .memberships import MembershipRepository, membership_repository
from .models import ApiKey, Principal, User
from .permissions import ROLE_PERMISSIONS


class AuthorizationService:
    def __init__(self, memberships: MembershipRepository = membership_repository):
        self.memberships = memberships

    def principal_for_user(self, user: User) -> Principal:
        if user.status != UserStatus.ACTIVE:
            raise PermissionDeniedError("principal is not active")
        roles = list(user.platform_roles)
        permissions: set[str] = set()
        for role in roles:
            permissions.update(ROLE_PERMISSIONS.get(role, set()))
        return Principal(
            principal_id=user.user_id,
            principal_type=PrincipalType.USER,
            user_id=user.user_id,
            roles=roles,
            permissions=sorted(permissions),
            authenticated_at=datetime.now(UTC).isoformat(),
        )

    def principal_for_api_key(self, api_key: ApiKey) -> Principal:
        if api_key.status != ApiKeyStatus.ACTIVE:
            raise PermissionDeniedError("api key is not active")
        return Principal(
            principal_id=api_key.api_key_id,
            principal_type=PrincipalType.API_KEY,
            api_key_id=api_key.api_key_id,
            workspace_id=api_key.workspace_id,
            permissions=api_key.permissions,
        )

    def authorize(self, principal: Principal, permission: str, workspace_id: str | None = None) -> None:
        if principal.principal_type == PrincipalType.API_KEY:
            if workspace_id and principal.workspace_id != workspace_id:
                self._deny(principal, permission, workspace_id)
            if permission not in principal.permissions:
                self._deny(principal, permission, workspace_id)
            return
        if permission in principal.permissions:
            return
        if workspace_id and principal.user_id:
            for membership in self.memberships.list_by_user(principal.user_id):
                if membership.workspace_id == workspace_id and membership.status == MembershipStatus.ACTIVE:
                    if permission in ROLE_PERMISSIONS.get(membership.role, set()):
                        return
        self._deny(principal, permission, workspace_id)

    def _deny(self, principal: Principal, permission: str, workspace_id: str | None) -> None:
        platform_audit(
            "authorization_denied",
            actor=principal.principal_id,
            target_type="permission",
            target_id=permission,
            workspace_id=workspace_id,
            result="denied",
        )
        raise PermissionDeniedError("permission denied")


authorization_service = AuthorizationService()
