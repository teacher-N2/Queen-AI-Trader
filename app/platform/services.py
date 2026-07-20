from datetime import UTC, datetime, timedelta
import re

from ..config import settings
from .audit import platform_audit
from .authorization import AuthorizationService, authorization_service
from .enums import MembershipStatus, PlatformRole, SettingClassification, UserStatus, WorkspaceStatus
from .errors import AccountLockedError, BootstrapError, InvalidCredentialsError, WorkspaceAlreadyExistsError
from .memberships import MembershipRepository, membership_repository
from .models import PlatformSetting, User, Workspace, WorkspaceMembership
from .security import normalize_email, password_service, token_service
from .settings_repository import SettingsRepository, settings_repository
from .user_repository import UserRepository, user_repository
from .workspace_repository import WorkspaceRepository, workspace_repository


def normalize_slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9-]+", "-", value.strip().lower()).strip("-")
    return slug or "workspace"


class UserService:
    def __init__(self, users: UserRepository = user_repository):
        self.users = users

    def create_user(self, *, email: str, display_name: str, password: str, platform_roles: list[PlatformRole] | None = None, status: UserStatus = UserStatus.ACTIVE) -> User:
        normalized = normalize_email(email)
        user = User(
            email=email,
            normalized_email=normalized,
            display_name=display_name,
            password_hash=password_service.hash_password(password),
            status=status,
            platform_roles=platform_roles or [],
            is_platform_admin=bool(platform_roles),
        )
        created = self.users.create(user)
        platform_audit("user_created", target_type="user", target_id=created.user_id)
        return created

    def login(self, *, email: str, password: str) -> tuple[User, str]:
        normalized = normalize_email(email)
        user = self.users.get_by_normalized_email(normalized)
        generic = InvalidCredentialsError("invalid credentials")
        if not user:
            platform_audit("login_failed", target_type="user", target_id=normalized, result="failed")
            raise generic
        if user.status == UserStatus.LOCKED:
            if user.locked_until:
                if datetime.fromisoformat(user.locked_until) > datetime.now(UTC):
                    platform_audit("login_locked", target_type="user", target_id=user.user_id, result="locked")
                    raise AccountLockedError("account locked")
                user.status = UserStatus.ACTIVE
                user.locked_until = None
                user.failed_login_attempts = 0
                self.users.update(user)
                platform_audit("account_lock_expired", target_type="user", target_id=user.user_id, result="unlocked")
            else:
                platform_audit("login_failed", target_type="user", target_id=user.user_id, result="administratively_locked")
                raise generic
        if user.status in {UserStatus.DISABLED, UserStatus.DELETED}:
            platform_audit("login_failed", target_type="user", target_id=user.user_id, result="unavailable")
            raise generic
        if not password_service.verify_password(password, user.password_hash):
            user.failed_login_attempts += 1
            if user.failed_login_attempts >= settings.login_max_failures:
                user.status = UserStatus.LOCKED
                user.locked_until = (datetime.now(UTC) + timedelta(minutes=settings.login_lockout_minutes)).isoformat()
            self.users.update(user)
            platform_audit("login_failed", target_type="user", target_id=user.user_id, result="failed")
            raise generic
        user.failed_login_attempts = 0
        user.locked_until = None
        user.last_login_at = datetime.now(UTC).isoformat()
        if user.status == UserStatus.PENDING:
            user.status = UserStatus.ACTIVE
        if password_service.needs_upgrade(user.password_hash):
            user.password_hash = password_service.upgrade_hash(password)
        self.users.update(user)
        token = token_service.create_access_token(user.user_id, [role.value for role in user.platform_roles])
        platform_audit("login_succeeded", actor=user.user_id, target_type="user", target_id=user.user_id)
        return user, token


class WorkspaceService:
    def __init__(
        self,
        workspaces: WorkspaceRepository = workspace_repository,
        memberships: MembershipRepository = membership_repository,
    ):
        self.workspaces = workspaces
        self.memberships = memberships

    def create_workspace(self, *, name: str, created_by_user_id: str, slug: str | None = None) -> Workspace:
        owned_count = sum(
            1
            for workspace in self.workspaces.list(limit=100)
            if workspace.created_by_user_id == created_by_user_id and workspace.status == WorkspaceStatus.ACTIVE
        )
        if owned_count >= settings.maximum_workspaces_per_user:
            raise WorkspaceAlreadyExistsError("workspace limit reached")
        workspace = Workspace(name=name, slug=normalize_slug(slug or name), created_by_user_id=created_by_user_id)
        created = self.workspaces.create(workspace)
        self.memberships.create(
            WorkspaceMembership(
                workspace_id=created.workspace_id,
                user_id=created_by_user_id,
                role=PlatformRole.WORKSPACE_OWNER,
                status=MembershipStatus.ACTIVE,
                invited_by_user_id=created_by_user_id,
            )
        )
        platform_audit("workspace_created", actor=created_by_user_id, target_type="workspace", target_id=created.workspace_id, workspace_id=created.workspace_id)
        return created

    def archive_workspace(self, workspace_id: str, actor: str) -> Workspace:
        workspace = self.workspaces.get_by_id(workspace_id)
        workspace.status = WorkspaceStatus.ARCHIVED
        updated = self.workspaces.update(workspace)
        platform_audit("workspace_archived", actor=actor, target_type="workspace", target_id=workspace_id, workspace_id=workspace_id)
        return updated


class PlatformSettingsService:
    def __init__(self, repository: SettingsRepository = settings_repository):
        self.repository = repository

    def defaults(self) -> None:
        defaults = {
            "platform_name": (settings.platform_name, SettingClassification.PUBLIC),
            "default_timezone": (settings.default_timezone, SettingClassification.PUBLIC),
            "default_locale": (settings.default_locale, SettingClassification.PUBLIC),
            "maintenance_mode": (False, SettingClassification.INTERNAL),
            "registration_enabled": (False, SettingClassification.INTERNAL),
            "maximum_workspaces_per_user": (settings.maximum_workspaces_per_user, SettingClassification.INTERNAL),
            "maximum_api_keys_per_workspace": (settings.max_api_keys_per_workspace, SettingClassification.INTERNAL),
        }
        for key, (value, classification) in defaults.items():
            if not self.repository.get(key):
                self.repository.set(PlatformSetting(key=key, value=value, classification=classification))

    def list_safe(self) -> list[PlatformSetting]:
        return [setting for setting in self.repository.list() if setting.classification != SettingClassification.SECRET]

    def set(self, key: str, value, actor: str | None = None) -> PlatformSetting:
        existing = self.repository.get(key)
        setting = existing or PlatformSetting(key=key, value=value, classification=SettingClassification.INTERNAL)
        setting.value = value
        setting.updated_at = datetime.now(UTC).isoformat()
        setting.updated_by = actor
        setting.version += 1
        saved = self.repository.set(setting)
        platform_audit("platform_setting_changed", actor=actor, target_type="setting", target_id=key)
        return saved


class BootstrapService:
    def __init__(self, users: UserRepository = user_repository, user_service: UserService | None = None):
        self.users = users
        self.user_service = user_service or UserService(users)

    def bootstrap_from_settings(self) -> User | None:
        if not settings.platform_bootstrap_enabled:
            return None
        if self.users.list(limit=1):
            raise BootstrapError("platform already bootstrapped")
        if not settings.platform_bootstrap_email or not settings.platform_bootstrap_password:
            raise BootstrapError("bootstrap email and password are required")
        user = self.user_service.create_user(
            email=settings.platform_bootstrap_email,
            display_name="Platform Owner",
            password=settings.platform_bootstrap_password,
            platform_roles=[PlatformRole.PLATFORM_OWNER],
            status=UserStatus.ACTIVE,
        )
        platform_audit("bootstrap_completed", actor=user.user_id, target_type="user", target_id=user.user_id)
        return user


user_service = UserService()
workspace_service = WorkspaceService()
platform_settings_service = PlatformSettingsService()
bootstrap_service = BootstrapService()
