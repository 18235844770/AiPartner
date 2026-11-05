import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.identity.repositories.models import User


class UserRepository:
    async def add(self, session: AsyncSession, user: User) -> User:
        session.add(user)
        await session.flush()
        return user

    async def get(self, session: AsyncSession, user_id: uuid.UUID) -> User | None:
        return await session.get(User, user_id)
