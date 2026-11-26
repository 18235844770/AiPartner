import uuid
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.identity.repositories.models import AuthSession, User


class AuthRepository:
    async def get_account(
        self, session: AsyncSession, username: str, *, lock: bool = False,
    ) -> User | None:
        query = select(User).where(User.username == username)
        return await session.scalar(query.with_for_update().execution_options(populate_existing=True) if lock else query)

    async def get_active_user(
        self, session: AsyncSession, user_id: uuid.UUID, *, lock: bool = False,
    ) -> User | None:
        query = select(User).where(User.id == user_id, User.status == "active", User.username.is_not(None))
        return await session.scalar(query.with_for_update().execution_options(populate_existing=True) if lock else query)

    async def get_by_access(self, session: AsyncSession, token_hash: str, now: datetime) -> AuthSession | None:
        return await session.scalar(
            select(AuthSession).join(User, User.id == AuthSession.user_id).where(
                AuthSession.access_token_hash == token_hash,
                AuthSession.revoked_at.is_(None),
                AuthSession.access_expires_at > now,
                AuthSession.expires_at > now,
                User.status == "active",
            ),
        )

    async def get_by_refresh(self, session: AsyncSession, token_hash: str, now: datetime) -> AuthSession | None:
        return await session.scalar(
            select(AuthSession).where(
                AuthSession.refresh_token_hash == token_hash,
                AuthSession.revoked_at.is_(None),
                AuthSession.expires_at > now,
            ),
        )

    async def rotate(
        self, session: AsyncSession, device: AuthSession, old_hash: str, new_access_hash: str,
        new_refresh_hash: str, access_expires_at: datetime, now: datetime,
    ) -> bool:
        statement = update(AuthSession).where(
            AuthSession.id == device.id, AuthSession.refresh_token_hash == old_hash,
            AuthSession.revoked_at.is_(None), AuthSession.expires_at > now,
        ).values(
            access_token_hash=new_access_hash,
            refresh_token_hash=new_refresh_hash,
            access_expires_at=access_expires_at,
        ).returning(AuthSession.id)
        return await session.scalar(statement) is not None

    async def revoke(self, session: AsyncSession, session_id: uuid.UUID, now: datetime) -> None:
        await session.execute(
            update(AuthSession).where(AuthSession.id == session_id, AuthSession.revoked_at.is_(None))
            .values(revoked_at=now),
        )

    async def revoke_others(
        self, session: AsyncSession, user_id: uuid.UUID, keep_session_id: uuid.UUID, now: datetime,
    ) -> None:
        await session.execute(
            update(AuthSession).where(
                AuthSession.user_id == user_id, AuthSession.id != keep_session_id, AuthSession.revoked_at.is_(None),
            ).values(revoked_at=now),
        )

    async def revoke_all(self, session: AsyncSession, user_id: uuid.UUID, now: datetime) -> None:
        await session.execute(update(AuthSession).where(
            AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None),
        ).values(revoked_at=now))
