import hashlib
import hmac
import re
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

from ..config import settings
from ..production_errors import ConfigurationError
from .errors import InvalidCredentialsError, PlatformSettingError

try:
    import bcrypt
except ModuleNotFoundError:
    bcrypt = None  # type: ignore[assignment]

try:
    import jwt
    from jwt import (
        DecodeError,
        ExpiredSignatureError,
        ImmatureSignatureError,
        InvalidAlgorithmError,
        InvalidAudienceError,
        InvalidIssuedAtError,
        InvalidIssuerError,
        InvalidSignatureError,
        MissingRequiredClaimError,
    )
except ModuleNotFoundError:
    jwt = None  # type: ignore[assignment]
    DecodeError = ExpiredSignatureError = ImmatureSignatureError = InvalidAlgorithmError = InvalidAudienceError = InvalidIssuedAtError = InvalidIssuerError = InvalidSignatureError = MissingRequiredClaimError = None  # type: ignore[assignment]


def ensure_platform_dependencies() -> None:
    if bcrypt is None:
        raise ConfigurationError("bcrypt is required when platform authentication is enabled")
    if jwt is None:
        raise ConfigurationError("PyJWT is required when platform authentication is enabled")


def normalize_email(email: str) -> str:
    return email.strip().lower()


class PasswordService:
    def validate_policy(self, password: str) -> None:
        if len(password) < settings.password_min_length or len(password) > settings.password_max_length:
            raise PlatformSettingError("password does not satisfy length policy")
        if settings.password_require_uppercase and not re.search(r"[A-Z]", password):
            raise PlatformSettingError("password does not satisfy complexity policy")
        if settings.password_require_lowercase and not re.search(r"[a-z]", password):
            raise PlatformSettingError("password does not satisfy complexity policy")
        if settings.password_require_numeric and not re.search(r"\d", password):
            raise PlatformSettingError("password does not satisfy complexity policy")
        if settings.password_require_special and not re.search(r"[^A-Za-z0-9]", password):
            raise PlatformSettingError("password does not satisfy complexity policy")

    def hash_password(self, password: str) -> str:
        self.validate_policy(password)
        return self._bcrypt_hash(password)

    def verify_password(self, password: str, password_hash: str) -> bool:
        if password_hash.startswith("$2") and bcrypt is not None:
            return bool(bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8")))
        if password_hash.startswith("pbkdf2_sha256$"):
            _, rounds, salt_b64, digest_b64 = password_hash.split("$", 3)
            import base64

            digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), base64.b64decode(salt_b64), int(rounds))
            return hmac.compare_digest(base64.b64encode(digest).decode(), digest_b64)
        return False

    def needs_upgrade(self, password_hash: str) -> bool:
        return bcrypt is not None and not password_hash.startswith("$2")

    def upgrade_hash(self, password: str) -> str:
        return self._bcrypt_hash(password)

    def _bcrypt_hash(self, password: str) -> str:
        if bcrypt is None:
            raise ConfigurationError("bcrypt is required for password hashing")
        return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


class TokenService:
    def create_access_token(self, user_id: str, roles: list[str]) -> str:
        now = datetime.now(UTC)
        claims = {
            "iss": settings.access_token_issuer,
            "aud": settings.access_token_audience,
            "sub": user_id,
            "jti": secrets.token_urlsafe(16),
            "roles": roles,
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(minutes=settings.access_token_expire_minutes)).timestamp()),
        }
        if jwt is None:
            raise ConfigurationError("PyJWT is required for access-token creation")
        return jwt.encode(claims, settings.access_token_secret, algorithm=settings.access_token_algorithm)

    def verify_access_token(self, token: str) -> dict[str, Any]:
        if jwt is None:
            raise ConfigurationError("PyJWT is required for access-token verification")
        try:
            header = jwt.get_unverified_header(token)
            if header.get("alg") != settings.access_token_algorithm or settings.access_token_algorithm not in {"HS256"}:
                raise InvalidAlgorithmError("unsupported token algorithm")
            claims = jwt.decode(
                token,
                settings.access_token_secret,
                algorithms=[settings.access_token_algorithm],
                audience=settings.access_token_audience,
                issuer=settings.access_token_issuer,
                options={"require": ["exp", "iat", "iss", "aud", "sub", "jti"], "verify_iat": False},
            )
            if int(claims["iat"]) > int(datetime.now(UTC).timestamp()) + settings.access_token_iat_leeway_seconds:
                raise ImmatureSignatureError("token issued in the future")
            if not str(claims.get("sub", "")).strip():
                raise MissingRequiredClaimError("sub")
            if not str(claims.get("jti", "")).strip():
                raise MissingRequiredClaimError("jti")
            return claims
        except (
            DecodeError,
            ExpiredSignatureError,
            ImmatureSignatureError,
            InvalidAlgorithmError,
            InvalidAudienceError,
            InvalidIssuedAtError,
            InvalidIssuerError,
            InvalidSignatureError,
            MissingRequiredClaimError,
        ) as exc:
            raise InvalidCredentialsError("invalid credentials") from exc


password_service = PasswordService()
token_service = TokenService()
