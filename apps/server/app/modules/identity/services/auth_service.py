import hashlib
import secrets
import unicodedata
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.modules.identity.repositories.auth_repository import AuthRepository
from app.modules.identity.repositories.companion_repository import CompanionRepository
from app.modules.identity.repositories.models import AuthSession, Companion, User
from app.modules.identity.repositories.user_repository import UserRepository
from app.shared.exceptions.errors import CredentialsRejectedError, UnauthorizedError


ACCESS_LIFETIME = timedelta(minutes=15)
DEVICE_LIFETIME = timedelta(days=30)
_passwords = PasswordHasher()
_dummy_password_hash = _passwords.hash(secrets.token_urlsafe(32))


@dataclass(frozen=True)
class AccountPrincipal:
    user_id: uuid.UUID
    session_id: uuid.UUID


@dataclass(frozen=True, repr=False)
class SessionTokens:
    access: str
    refresh: str
    access_expires_at: datetime
    expires_at: datetime


def normalize_username(value: str) -> str:
    return unicodedata.normalize("NFKC", value).strip().casefold()


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _new_tokens(now: datetime, expires_at: datetime) -> SessionTokens:
    return SessionTokens(
        secrets.token_urlsafe(32), secrets.token_urlsafe(32), min(now + ACCESS_LIFETIME, expires_at), expires_at,
    )


def _verify(password_hash: str, password: str) -> bool:
    try:
        return _passwords.verify(password_hash, password)
    except (VerificationError, ValueError):
        return False


class AuthService:
    def __init__(self) -> None:
        self._repository = AuthRepository()
        self._users = UserRepository()
        self._companions = CompanionRepository()

    async def register(
        self, session: AsyncSession, username: str, password: str, display_name: str, timezone: str,
    ) -> uuid.UUID | None:
        password_hash = await run_in_threadpool(_passwords.hash, password)
        try:
            async with session.begin():
                user = await self._users.add(session, User(
                    username=username, password_hash=password_hash, display_name=display_name, timezone=timezone,
                ))
                await self._companions.add(session, Companion(
                    owner_user_id=user.id, name="伴侣", is_default=True, initialization_status="pending",
                ))
            return user.id
        except IntegrityError as exc:
            driver_error = getattr(exc.orig, "__cause__", None)
            if getattr(driver_error, "constraint_name", None) != "uq_users_username":
                raise
            return None

    async def login(self, session: AsyncSession, username: str, password: str) -> SessionTokens:
        async with session.begin():
            user = await self._repository.get_account(session, username)
            stored_hash = user.password_hash if user else None
        password_valid = await run_in_threadpool(_verify, stored_hash or _dummy_password_hash, password)
        if not stored_hash or not password_valid:
            raise UnauthorizedError("账号或密码不正确")

        now = datetime.now(UTC)
        tokens = _new_tokens(now, now + DEVICE_LIFETIME)
        async with session.begin():
            user = await self._repository.get_account(session, username, lock=True)
            if user is None or user.status != "active" or user.password_hash != stored_hash:
                raise UnauthorizedError("账号或密码不正确")
            user.last_login_at = now
            session.add(AuthSession(
                user_id=user.id, access_token_hash=token_hash(tokens.access), refresh_token_hash=token_hash(tokens.refresh),
                access_expires_at=tokens.access_expires_at, expires_at=tokens.expires_at, created_at=now,
            ))
        return tokens

    async def refresh(self, session: AsyncSession, refresh: str) -> SessionTokens:
        now = datetime.now(UTC)
        old_hash = token_hash(refresh)
        async with session.begin():
            device = await self._repository.get_by_refresh(session, old_hash, now)
            if device is None or await self._repository.get_active_user(session, device.user_id, lock=True) is None:
                raise UnauthorizedError("登录会话已失效")
            tokens = _new_tokens(now, device.expires_at)
            rotated = await self._repository.rotate(
                session, device, old_hash, token_hash(tokens.access), token_hash(tokens.refresh), tokens.access_expires_at, now,
            )
            if not rotated:
                raise UnauthorizedError("登录会话已失效")
        return tokens

    async def authenticate(self, session: AsyncSession, access: str) -> AccountPrincipal:
        async with session.begin():
            device = await self._repository.get_by_access(session, token_hash(access), datetime.now(UTC))
            if device is None:
                raise UnauthorizedError("登录会话已失效")
            return AccountPrincipal(device.user_id, device.id)

    async def logout(
        self, session: AsyncSession, access: str | None, refresh: str | None, expected_user: str | None = None,
    ) -> None:
        now = datetime.now(UTC)
        async with session.begin():
            device = await self._repository.get_by_access(session, token_hash(access), now) if access else None
            if device is None and refresh:
                device = await self._repository.get_by_refresh(session, token_hash(refresh), now)
            if device is not None:
                if expected_user is not None and expected_user != str(device.user_id):
                    raise UnauthorizedError("当前账号已切换，请重新登录")
                await self._repository.revoke(session, device.id, now)

    async def get_user(self, session: AsyncSession, principal: AccountPrincipal) -> User:
        async with session.begin():
            return await self._require_user(session, principal)

    async def update_profile(self, session: AsyncSession, principal: AccountPrincipal, changes: dict) -> User:
        async with session.begin():
            user = await self._require_user(session, principal, lock=True)
            for field in ("display_name", "timezone", "avatar_url"):
                if field in changes:
                    setattr(user, field, changes[field])
            return user

    async def change_password(
        self, session: AsyncSession, principal: AccountPrincipal, current: str, new: str,
    ) -> None:
        user = await self.get_user(session, principal)
        stored_hash = user.password_hash
        if not stored_hash or not await run_in_threadpool(_verify, stored_hash, current):
            raise CredentialsRejectedError("当前密码不正确")
        replacement = await run_in_threadpool(_passwords.hash, new)
        async with session.begin():
            locked_user = await self._require_user(session, principal, lock=True)
            if locked_user.password_hash != stored_hash:
                raise CredentialsRejectedError("当前密码不正确")
            locked_user.password_hash = replacement
            await self._repository.revoke_others(session, principal.user_id, principal.session_id, datetime.now(UTC))

    async def request_deletion(self, session: AsyncSession, principal: AccountPrincipal, password: str) -> None:
        user = await self.get_user(session, principal)
        stored_hash = user.password_hash
        if not stored_hash or not await run_in_threadpool(_verify, stored_hash, password):
            raise CredentialsRejectedError("当前密码不正确")
        async with session.begin():
            locked_user = await self._require_user(session, principal, lock=True)
            if locked_user.password_hash != stored_hash:
                raise CredentialsRejectedError("当前密码不正确")
            locked_user.status = "deleting"
            await self._repository.revoke_all(session, principal.user_id, datetime.now(UTC))

    async def _require_user(
        self, session: AsyncSession, principal: AccountPrincipal, *, lock: bool = False,
    ) -> User:
        user = await self._repository.get_active_user(session, principal.user_id, lock=lock)
        if user is None:
            raise UnauthorizedError("登录会话已失效")
        return user
