import logging
import random
import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.identity.services.identity_service import IdentityService
from app.modules.persona.api.schemas import CreatePersonaVersionRequest, InitializePersonaRequest, PersonaResponse, PersonaVersionResponse
from app.modules.persona.domain.enums import MbtiType
from app.modules.persona.domain.templates import PersonaTemplate, load_persona_templates
from app.modules.persona.repositories.models import PersonaProfile, PersonaVersion
from app.modules.persona.repositories.persona_repository import PersonaRepository
from app.shared.exceptions.errors import ConflictError, NotFoundError

logger = logging.getLogger(__name__)

INITIAL_CHANGE_REASON = "初始人格"


class PersonaService:
    def __init__(
        self,
        personas: PersonaRepository | None = None,
        identity: IdentityService | None = None,
        rng: random.Random | None = None,
    ) -> None:
        self._personas = personas or PersonaRepository()
        self._identity = identity or IdentityService()
        self._rng = rng or random.SystemRandom()
        self._templates = load_persona_templates()

    async def initialize(
        self,
        session: AsyncSession,
        user_id: uuid.UUID,
        companion_id: uuid.UUID,
        data: InitializePersonaRequest,
    ) -> tuple[PersonaProfile, PersonaVersion]:
        async with session.begin():
            await self._identity.get_owned_companion(session, user_id, companion_id)
            existing = await self._personas.get_by_companion(session, companion_id)
            if existing is not None:
                raise ConflictError("人格已经初始化")
            mbti_type = data.mbti_type or self._rng.choice(list(MbtiType))
            profile, version = self._new_profile(companion_id, self._templates[mbti_type])
            await self._personas.add_profile(session, profile)
            await self._personas.add_version(session, version)
        logger.info("initialized persona %s for companion %s", profile.id, companion_id)
        return profile, version

    async def get_current(
        self,
        session: AsyncSession,
        user_id: uuid.UUID,
        companion_id: uuid.UUID,
    ) -> tuple[PersonaProfile, PersonaVersion]:
        if session.in_transaction():
            await self._identity.get_owned_companion(session, user_id, companion_id)
            return await self._require_current(session, companion_id)
        async with session.begin():
            await self._identity.get_owned_companion(session, user_id, companion_id)
            return await self._require_current(session, companion_id)

    async def add_version(
        self,
        session: AsyncSession,
        user_id: uuid.UUID,
        companion_id: uuid.UUID,
        data: CreatePersonaVersionRequest,
    ) -> tuple[PersonaProfile, PersonaVersion]:
        async with session.begin():
            await self._identity.get_owned_companion(session, user_id, companion_id)
            profile, current = await self._require_current(session, companion_id)
            version = PersonaVersion(
                persona_profile_id=profile.id,
                version_number=current.version_number + 1,
                mbti_type=current.mbti_type,
                core_traits=_replace_traits(current.core_traits, data.core_traits),
                behavior_traits=_replace_traits(current.behavior_traits, data.behavior_traits),
                communication_preferences=_replace_traits(
                    current.communication_preferences,
                    data.communication_preferences,
                ),
                archive=current.archive if data.archive is None else data.archive.dump(),
                change_reason=data.change_reason,
            )
            await self._personas.add_version(session, version)
            profile.current_version_id = version.id
            profile.updated_at = datetime.now(UTC)
            await session.flush()
        logger.info("added persona version %s for profile %s", version.id, profile.id)
        return profile, version

    async def _require_current(
        self,
        session: AsyncSession,
        companion_id: uuid.UUID,
    ) -> tuple[PersonaProfile, PersonaVersion]:
        profile = await self._personas.get_by_companion(session, companion_id)
        if profile is None:
            raise NotFoundError("人格不存在")
        version = await self._personas.get_version(session, profile.current_version_id)
        if version is None or version.persona_profile_id != profile.id:
            raise NotFoundError("人格不存在")
        return profile, version

    def _new_profile(self, companion_id: uuid.UUID, template: PersonaTemplate) -> tuple[PersonaProfile, PersonaVersion]:
        profile_id = uuid.uuid4()
        version_id = uuid.uuid4()
        profile = PersonaProfile(
            id=profile_id,
            companion_id=companion_id,
            initial_version_id=version_id,
            current_version_id=version_id,
        )
        version = PersonaVersion(
            id=version_id,
            persona_profile_id=profile_id,
            version_number=1,
            mbti_type=template.mbti_type.value,
            core_traits={
                "title": template.title,
                "summary": template.summary,
                "values": list(template.archive.values),
                "thinking_habits": list(template.archive.thinking_habits),
            },
            behavior_traits={"attention": list(template.archive.attention)},
            communication_preferences={
                "summary": template.expression,
                "communication": template.archive.communication,
            },
            archive=template.archive.dump(),
            change_reason=INITIAL_CHANGE_REASON,
        )
        return profile, version


def to_persona_response(profile: PersonaProfile, version: PersonaVersion) -> PersonaResponse:
    return PersonaResponse(
        id=profile.id,
        companion_id=profile.companion_id,
        initial_version_id=profile.initial_version_id,
        current_version_id=profile.current_version_id,
        current_version=to_version_response(version),
        created_at=profile.created_at,
        updated_at=profile.updated_at,
    )


def to_version_response(version: PersonaVersion) -> PersonaVersionResponse:
    return PersonaVersionResponse(
        id=version.id,
        persona_profile_id=version.persona_profile_id,
        version_number=version.version_number,
        mbti_type=version.mbti_type,
        core_traits=version.core_traits,
        behavior_traits=version.behavior_traits,
        communication_preferences=version.communication_preferences,
        archive=dict(version.archive),
        change_reason=version.change_reason,
        created_at=version.created_at,
    )


def _replace_traits(current: dict[str, object], replacement: dict[str, object] | None) -> dict[str, object]:
    if replacement is None:
        return dict(current)
    return dict(replacement)
