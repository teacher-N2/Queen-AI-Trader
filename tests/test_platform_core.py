import base64
import hashlib
import hmac
import inspect
from datetime import UTC, datetime, timedelta
import tempfile
import unittest
import warnings
from pathlib import Path

from app.config import Settings
from app.observability import redact
from app.production_errors import ConfigurationError
from app.platform.api_key_repository import ApiKeyRepository
from app.platform.api_keys import ApiKeyService
from app.platform.authorization import AuthorizationService
from app.platform.enums import MembershipStatus, PlatformRole, UserStatus
from app.platform.errors import (
    ApiKeyConflictError,
    ApiKeyRevokedError,
    FinalWorkspaceOwnerError,
    AccountLockedError,
    InvalidCredentialsError,
    MembershipConflictError,
    PermissionDeniedError,
    UserAlreadyExistsError,
    WorkspaceAlreadyExistsError,
)
from app.platform.memberships import MembershipRepository
from app.platform.models import ApiKey, PlatformSetting, User, Workspace, WorkspaceMembership
from app.platform.permissions import API_KEYS_READ, PLATFORM_MANAGE, WORKSPACES_READ, WORKSPACES_UPDATE
from app.platform.repository import JsonRepository
import app.platform.security as security_module
import app.platform.services as services_module
from app.platform.services import BootstrapService, PlatformSettingsService, UserService, WorkspaceService
from app.platform.settings_repository import SettingsRepository
from app.platform.user_repository import UserRepository
from app.platform.workspace_repository import WorkspaceRepository


PASSWORD = "correct horse battery"
STRONG_SECRET = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
PINE_ENGINE_SHA256 = "56db258a57a0cbd02fae3c88d918ab7593835383f07a4b38997def44a53a1852"


class FakeBcrypt:
    @staticmethod
    def gensalt():
        return b"fake-salt"

    @staticmethod
    def hashpw(password: bytes, salt: bytes):
        digest = hashlib.sha256(password + salt).hexdigest().encode("ascii")
        return b"$2b$fake$" + digest

    @staticmethod
    def checkpw(password: bytes, password_hash: bytes):
        return hmac.compare_digest(FakeBcrypt.hashpw(password, b"fake-salt"), password_hash)


class FakeTokenService:
    def create_access_token(self, user_id: str, roles: list[str]) -> str:
        return f"test-token:{user_id}"


class PlatformCoreTests(unittest.TestCase):
    def setUp(self):
        self.original_bcrypt = security_module.bcrypt
        self.original_token_service = services_module.token_service
        self.original_platform_audit = services_module.platform_audit
        self.original_security_settings = security_module.settings
        security_module.settings = Settings(access_token_secret=STRONG_SECRET)
        if security_module.bcrypt is None:
            security_module.bcrypt = FakeBcrypt
        if security_module.jwt is None:
            services_module.token_service = FakeTokenService()
        self.audit_events = []

        def capture_audit(event_name, **fields):
            self.audit_events.append((event_name, fields))

        services_module.platform_audit = capture_audit

    def tearDown(self):
        security_module.bcrypt = self.original_bcrypt
        services_module.token_service = self.original_token_service
        services_module.platform_audit = self.original_platform_audit
        security_module.settings = self.original_security_settings

    def make_stack(self, tmpdir: str):
        base = Path(tmpdir)
        users = UserRepository(JsonRepository("users.json", model=User, storage_dir=base))
        workspaces = WorkspaceRepository(JsonRepository("workspaces.json", model=Workspace, storage_dir=base))
        memberships = MembershipRepository(JsonRepository("memberships.json", model=WorkspaceMembership, storage_dir=base))
        api_keys = ApiKeyRepository(JsonRepository("api_keys.json", model=ApiKey, storage_dir=base))
        platform_settings = SettingsRepository(JsonRepository("settings.json", model=PlatformSetting, storage_dir=base))
        user_service = UserService(users)
        workspace_service = WorkspaceService(workspaces, memberships)
        authorization = AuthorizationService(memberships)
        api_key_service = ApiKeyService(api_keys)
        settings_service = PlatformSettingsService(platform_settings)
        bootstrap_service = BootstrapService(users, user_service)
        return users, workspaces, memberships, api_keys, platform_settings, user_service, workspace_service, authorization, api_key_service, settings_service, bootstrap_service

    def test_user_creation_normalizes_email_and_hashes_password(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            users, _, _, _, _, user_service, _, _, _, _, _ = self.make_stack(tmpdir)
            user = user_service.create_user(email=" Owner@Example.COM ", display_name="Owner", password=PASSWORD, platform_roles=[PlatformRole.PLATFORM_OWNER])
            self.assertEqual(user.normalized_email, "owner@example.com")
            self.assertNotEqual(user.password_hash, PASSWORD)
            with self.assertRaises(UserAlreadyExistsError):
                user_service.create_user(email="owner@example.com", display_name="Owner 2", password=PASSWORD)
            self.assertEqual(users.get_by_normalized_email("owner@example.com").user_id, user.user_id)

    def test_login_success_failure_lockout_and_disabled_status(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            users, _, _, _, _, user_service, _, _, _, _, _ = self.make_stack(tmpdir)
            user = user_service.create_user(email="user@example.com", display_name="User", password=PASSWORD)
            logged_in, token = user_service.login(email=" USER@example.com ", password=PASSWORD)
            self.assertEqual(logged_in.user_id, user.user_id)
            self.assertTrue(token)
            with self.assertRaises(InvalidCredentialsError):
                user_service.login(email="user@example.com", password="wrong password")
            users.disable(user.user_id)
            with self.assertRaises(InvalidCredentialsError):
                user_service.login(email="user@example.com", password=PASSWORD)

    def test_login_rejected_before_lock_expiry(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            users, _, _, _, _, user_service, _, _, _, _, _ = self.make_stack(tmpdir)
            user = user_service.create_user(email="locked@example.com", display_name="Locked", password=PASSWORD)
            user.status = UserStatus.LOCKED
            user.locked_until = (datetime.now(UTC) + timedelta(minutes=10)).isoformat()
            user.failed_login_attempts = 5
            users.update(user)
            with self.assertRaises(AccountLockedError):
                user_service.login(email="locked@example.com", password=PASSWORD)
            reloaded = users.get_by_id(user.user_id)
            self.assertEqual(reloaded.status, UserStatus.LOCKED)
            self.assertEqual(reloaded.failed_login_attempts, 5)

    def test_login_succeeds_after_lock_expiry_and_resets_failures(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            users, _, _, _, _, user_service, _, _, _, _, _ = self.make_stack(tmpdir)
            user = user_service.create_user(email="expired@example.com", display_name="Expired", password=PASSWORD)
            user.status = UserStatus.LOCKED
            user.locked_until = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
            user.failed_login_attempts = 5
            users.update(user)
            logged_in, token = user_service.login(email="expired@example.com", password=PASSWORD)
            self.assertEqual(logged_in.status, UserStatus.ACTIVE)
            self.assertIsNone(logged_in.locked_until)
            self.assertEqual(logged_in.failed_login_attempts, 0)
            self.assertTrue(token)

    def test_wrong_password_after_auto_unlock_starts_new_failure_count(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            users, _, _, _, _, user_service, _, _, _, _, _ = self.make_stack(tmpdir)
            user = user_service.create_user(email="retry@example.com", display_name="Retry", password=PASSWORD)
            user.status = UserStatus.LOCKED
            user.locked_until = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
            user.failed_login_attempts = 5
            users.update(user)
            with self.assertRaises(InvalidCredentialsError):
                user_service.login(email="retry@example.com", password="wrong password")
            reloaded = users.get_by_id(user.user_id)
            self.assertEqual(reloaded.status, UserStatus.ACTIVE)
            self.assertEqual(reloaded.failed_login_attempts, 1)
            self.assertIsNone(reloaded.locked_until)

    def test_administrative_locked_user_without_expiry_remains_locked(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            users, _, _, _, _, user_service, _, _, _, _, _ = self.make_stack(tmpdir)
            user = user_service.create_user(email="admin-locked@example.com", display_name="Admin Locked", password=PASSWORD)
            user.status = UserStatus.LOCKED
            user.locked_until = None
            users.update(user)
            with self.assertRaises(InvalidCredentialsError):
                user_service.login(email="admin-locked@example.com", password=PASSWORD)
            self.assertEqual(users.get_by_id(user.user_id).status, UserStatus.LOCKED)

    def test_deleted_user_gets_generic_login_error(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            users, _, _, _, _, user_service, _, _, _, _, _ = self.make_stack(tmpdir)
            user = user_service.create_user(email="deleted@example.com", display_name="Deleted", password=PASSWORD)
            user.status = UserStatus.DELETED
            users.update(user)
            with self.assertRaises(InvalidCredentialsError):
                user_service.login(email="deleted@example.com", password=PASSWORD)

    def test_automatic_unlock_is_audited(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            users, _, _, _, _, user_service, _, _, _, _, _ = self.make_stack(tmpdir)
            user = user_service.create_user(email="audit-unlock@example.com", display_name="Audit", password=PASSWORD)
            user.status = UserStatus.LOCKED
            user.locked_until = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
            user.failed_login_attempts = 5
            users.update(user)
            user_service.login(email="audit-unlock@example.com", password=PASSWORD)
            self.assertIn("account_lock_expired", [event for event, _ in self.audit_events])

    def test_workspace_slug_uniqueness_and_owner_membership(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            _, _, memberships, _, _, user_service, workspace_service, _, _, _, _ = self.make_stack(tmpdir)
            owner = user_service.create_user(email="owner@example.com", display_name="Owner", password=PASSWORD)
            workspace = workspace_service.create_workspace(name="Queen Desk", created_by_user_id=owner.user_id)
            self.assertEqual(workspace.slug, "queen-desk")
            owner_memberships = memberships.list_by_user(owner.user_id)
            self.assertEqual(owner_memberships[0].role, PlatformRole.WORKSPACE_OWNER)
            with self.assertRaises(WorkspaceAlreadyExistsError):
                workspace_service.create_workspace(name="Queen Desk", created_by_user_id=owner.user_id)
            with self.assertRaises(FinalWorkspaceOwnerError):
                memberships.remove(owner_memberships[0].membership_id)

    def test_membership_rejects_platform_roles(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            _, _, memberships, _, _, user_service, workspace_service, _, _, _, _ = self.make_stack(tmpdir)
            owner = user_service.create_user(email="owner@example.com", display_name="Owner", password=PASSWORD)
            workspace = workspace_service.create_workspace(name="Desk", created_by_user_id=owner.user_id)
            with self.assertRaises(MembershipConflictError):
                memberships.create(WorkspaceMembership(workspace_id=workspace.workspace_id, user_id=owner.user_id, role=PlatformRole.PLATFORM_ADMIN))

    def test_authorization_denies_by_default_and_isolates_workspaces(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            _, _, memberships, _, _, user_service, workspace_service, authorization, _, _, _ = self.make_stack(tmpdir)
            owner = user_service.create_user(email="owner@example.com", display_name="Owner", password=PASSWORD)
            viewer = user_service.create_user(email="viewer@example.com", display_name="Viewer", password=PASSWORD)
            platform_owner = user_service.create_user(email="admin@example.com", display_name="Admin", password=PASSWORD, platform_roles=[PlatformRole.PLATFORM_OWNER])
            workspace = workspace_service.create_workspace(name="Desk", created_by_user_id=owner.user_id)
            other_workspace = workspace_service.create_workspace(name="Desk 2", created_by_user_id=owner.user_id)
            memberships.create(WorkspaceMembership(workspace_id=workspace.workspace_id, user_id=viewer.user_id, role=PlatformRole.VIEWER))

            viewer_principal = authorization.principal_for_user(viewer)
            authorization.authorize(viewer_principal, WORKSPACES_READ, workspace.workspace_id)
            with self.assertRaises(PermissionDeniedError):
                authorization.authorize(viewer_principal, WORKSPACES_UPDATE, workspace.workspace_id)
            with self.assertRaises(PermissionDeniedError):
                authorization.authorize(viewer_principal, WORKSPACES_READ, other_workspace.workspace_id)
            authorization.authorize(authorization.principal_for_user(platform_owner), PLATFORM_MANAGE)

    def test_inactive_user_cannot_become_principal(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            _, _, _, _, _, user_service, _, authorization, _, _, _ = self.make_stack(tmpdir)
            user = user_service.create_user(email="pending@example.com", display_name="Pending", password=PASSWORD, status=UserStatus.PENDING)
            with self.assertRaises(PermissionDeniedError):
                authorization.principal_for_user(user)

    def test_api_key_hashing_authentication_scope_and_revocation(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            _, _, _, api_keys, _, user_service, workspace_service, authorization, api_key_service, _, _ = self.make_stack(tmpdir)
            owner = user_service.create_user(email="owner@example.com", display_name="Owner", password=PASSWORD)
            workspace = workspace_service.create_workspace(name="Desk", created_by_user_id=owner.user_id)
            other_workspace = workspace_service.create_workspace(name="Other Desk", created_by_user_id=owner.user_id)
            key, secret = api_key_service.create_key(workspace_id=workspace.workspace_id, owner_user_id=owner.user_id, name="robot", permissions=[API_KEYS_READ])
            self.assertNotEqual(key.key_hash, secret)
            principal = authorization.principal_for_api_key(api_key_service.authenticate(secret))
            authorization.authorize(principal, API_KEYS_READ, workspace.workspace_id)
            with self.assertRaises(PermissionDeniedError):
                authorization.authorize(principal, API_KEYS_READ, other_workspace.workspace_id)
            api_keys.revoke(key.api_key_id)
            with self.assertRaises(ApiKeyRevokedError):
                api_key_service.authenticate(secret)

    def test_api_key_limit_is_enforced(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            _, _, _, _, _, user_service, workspace_service, _, api_key_service, _, _ = self.make_stack(tmpdir)
            owner = user_service.create_user(email="owner@example.com", display_name="Owner", password=PASSWORD)
            workspace = workspace_service.create_workspace(name="Desk", created_by_user_id=owner.user_id)
            for index in range(20):
                api_key_service.create_key(workspace_id=workspace.workspace_id, owner_user_id=owner.user_id, name=f"robot-{index}", permissions=[API_KEYS_READ])
            with self.assertRaises(ApiKeyConflictError):
                api_key_service.create_key(workspace_id=workspace.workspace_id, owner_user_id=owner.user_id, name="robot-over-limit", permissions=[API_KEYS_READ])

    def test_platform_settings_defaults_are_idempotent(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            _, _, _, _, platform_settings, _, _, _, _, settings_service, _ = self.make_stack(tmpdir)
            settings_service.defaults()
            first_count = len(platform_settings.list())
            settings_service.defaults()
            self.assertEqual(len(platform_settings.list()), first_count)
            self.assertIsNotNone(platform_settings.get("maintenance_mode"))
            updated = settings_service.set("maintenance_mode", True, actor="usr_test")
            self.assertTrue(updated.value)
            self.assertEqual(updated.updated_by, "usr_test")
            self.assertGreater(updated.version, 1)

    def test_new_password_hashes_use_bcrypt(self):
        password_hash = security_module.PasswordService().hash_password(PASSWORD)
        self.assertTrue(password_hash.startswith("$2"))

    def test_existing_legacy_pbkdf2_hash_verifies(self):
        salt = b"legacy-salt"
        digest = hashlib.pbkdf2_hmac("sha256", PASSWORD.encode("utf-8"), salt, 390000)
        legacy_hash = "pbkdf2_sha256$390000$" + base64.b64encode(salt).decode() + "$" + base64.b64encode(digest).decode()
        self.assertTrue(security_module.PasswordService().verify_password(PASSWORD, legacy_hash))

    def test_legacy_password_hash_upgrades_after_successful_login(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            users, _, _, _, _, user_service, _, _, _, _, _ = self.make_stack(tmpdir)
            user = user_service.create_user(email="legacy@example.com", display_name="Legacy", password=PASSWORD)
            salt = b"legacy-salt"
            digest = hashlib.pbkdf2_hmac("sha256", PASSWORD.encode("utf-8"), salt, 390000)
            user.password_hash = "pbkdf2_sha256$390000$" + base64.b64encode(salt).decode() + "$" + base64.b64encode(digest).decode()
            users.update(user)
            user_service.login(email="legacy@example.com", password=PASSWORD)
            self.assertTrue(users.get_by_id(user.user_id).password_hash.startswith("$2"))

    def test_missing_bcrypt_fails_clearly(self):
        security_module.bcrypt = None
        with self.assertRaises(ConfigurationError):
            security_module.ensure_platform_dependencies()
        with self.assertRaises(ConfigurationError):
            security_module.PasswordService().hash_password(PASSWORD)

    def test_custom_jwt_fallback_is_removed(self):
        source = inspect.getsource(security_module.TokenService)
        self.assertNotIn("fallback.", source)
        self.assertNotIn("literal_eval", source)

    @unittest.skipIf(security_module.jwt is None, "PyJWT is not installed in the local runtime")
    def test_missing_required_jwt_claim_is_rejected(self):
        token = self.encode_claims_without("jti")
        with self.assertRaises(InvalidCredentialsError):
            security_module.TokenService().verify_access_token(token)

    @unittest.skipIf(security_module.jwt is None, "PyJWT is not installed in the local runtime")
    def test_empty_subject_is_rejected(self):
        token = self.encode_claims({"sub": ""})
        with self.assertRaises(InvalidCredentialsError):
            security_module.TokenService().verify_access_token(token)

    @unittest.skipIf(security_module.jwt is None, "PyJWT is not installed in the local runtime")
    def test_invalid_issuer_is_rejected(self):
        token = self.encode_claims({"iss": "wrong-issuer"})
        with self.assertRaises(InvalidCredentialsError):
            security_module.TokenService().verify_access_token(token)

    @unittest.skipIf(security_module.jwt is None, "PyJWT is not installed in the local runtime")
    def test_invalid_audience_is_rejected(self):
        token = self.encode_claims({"aud": "wrong-audience"})
        with self.assertRaises(InvalidCredentialsError):
            security_module.TokenService().verify_access_token(token)

    @unittest.skipIf(security_module.jwt is None, "PyJWT is not installed in the local runtime")
    def test_unsupported_algorithm_is_rejected(self):
        token = security_module.jwt.encode(self.default_claims(), STRONG_SECRET, algorithm="HS384")
        with self.assertRaises(InvalidCredentialsError):
            security_module.TokenService().verify_access_token(token)

    @unittest.skipIf(security_module.jwt is None, "PyJWT is not installed in the local runtime")
    def test_expired_token_is_rejected(self):
        token = self.encode_claims({"exp": int((datetime.now(UTC) - timedelta(seconds=1)).timestamp())})
        with self.assertRaises(InvalidCredentialsError):
            security_module.TokenService().verify_access_token(token)

    @unittest.skipIf(security_module.jwt is None, "PyJWT is not installed in the local runtime")
    def test_future_issued_token_outside_tolerance_is_rejected(self):
        future = int((datetime.now(UTC) + timedelta(minutes=10)).timestamp())
        token = self.encode_claims({"iat": future, "exp": future + 600})
        with self.assertRaises(InvalidCredentialsError):
            security_module.TokenService().verify_access_token(token)

    @unittest.skipIf(security_module.jwt is None, "PyJWT is not installed in the local runtime")
    def test_invalid_signature_is_rejected(self):
        token = security_module.jwt.encode(self.default_claims(), STRONG_SECRET[::-1], algorithm="HS256")
        with self.assertRaises(InvalidCredentialsError):
            security_module.TokenService().verify_access_token(token)

    @unittest.skipIf(security_module.jwt is None, "PyJWT is not installed in the local runtime")
    def test_pyjwt_token_path_has_no_key_length_warning(self):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            token = security_module.TokenService().create_access_token("usr_test", [])
            self.assertTrue(token)
        self.assertEqual([warning for warning in caught if "key" in str(warning.message).lower()], [])

    def test_weak_production_jwt_secret_fails_startup(self):
        config = Settings(
            environment="production",
            webhook_shared_secret="webhook-secret",
            telegram_enabled=False,
            access_token_secret="too-short",
            allowed_hosts=("example.com",),
        )
        with self.assertRaises(ConfigurationError):
            config.validate_startup()

    def test_strong_production_jwt_secret_passes_validation(self):
        config = Settings(
            environment="production",
            webhook_shared_secret="webhook-secret",
            telegram_enabled=False,
            access_token_secret=STRONG_SECRET,
            allowed_hosts=("example.com",),
        )
        config.validate_startup()

    def test_security_redaction_covers_platform_credentials(self):
        payload = {
            "api_key": "qk_secret",
            "jwt": "header.payload.signature",
            "authorization": "Bearer token",
            "password": "plain-password",
            "nested": {"access_token": "token"},
            "safe": "ok",
        }
        redacted = redact(payload)
        self.assertEqual(redacted["api_key"], "[redacted]")
        self.assertEqual(redacted["jwt"], "[redacted]")
        self.assertEqual(redacted["authorization"], "[redacted]")
        self.assertEqual(redacted["password"], "[redacted]")
        self.assertEqual(redacted["nested"]["access_token"], "[redacted]")
        self.assertEqual(redacted["safe"], "ok")

    def test_pine_script_hash_remains_unchanged(self):
        pine_path = Path(__file__).resolve().parents[1] / "pine" / "Queen_Engine_v2.pine"
        digest = hashlib.sha256(pine_path.read_bytes()).hexdigest()
        self.assertEqual(digest, PINE_ENGINE_SHA256)

    def default_claims(self):
        now = datetime.now(UTC)
        return {
            "iss": "queen-ai-trader",
            "aud": "queen-platform",
            "sub": "usr_test",
            "jti": "jti-test",
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(minutes=5)).timestamp()),
        }

    def encode_claims(self, overrides: dict):
        claims = self.default_claims()
        claims.update(overrides)
        return security_module.jwt.encode(claims, STRONG_SECRET, algorithm="HS256")

    def encode_claims_without(self, claim_name: str):
        claims = self.default_claims()
        claims.pop(claim_name)
        return security_module.jwt.encode(claims, STRONG_SECRET, algorithm="HS256")


if __name__ == "__main__":
    unittest.main()
