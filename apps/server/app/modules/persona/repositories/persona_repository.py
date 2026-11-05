import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.persona.repositories.models import PersonaProfile, PersonaVersion


class PersonaRepository:
    async def add_profile(self, session: AsyncSession, profile: PersonaProfile) -> PersonaProfile:
        session.add(profile)
        await session.flush()
        return profile

    async def add_version(self, session: AsyncSession, version: PersonaVersion) -> PersonaVersion:
        session.add(version)
        await session.flush()
        return version

    async def get_by_companion(self, session: AsyncSession, companion_id: uuid.UUID) -> PersonaProfile | None:
        result = await session.scalars(select(PersonaProfile).where(PersonaProfile.companion_id == companion_id))
        return result.one_or_none()

    async def get_version(self, session: AsyncSession, version_id: uuid.UUID) -> PersonaVersion | None:
        return await session.get(PersonaVersion, version_id)
