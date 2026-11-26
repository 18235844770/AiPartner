import asyncio
import uuid
from collections.abc import AsyncIterator
from typing import Annotated, Literal

from fastapi import APIRouter, Query, Request, Response
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator
from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.config.settings import get_settings
from app.modules.audio.services.audio_manager import AudioManager
from app.modules.audio.domain.schemas import AudioHealthResponse, VoicePresetResponse, VoicePresetSelectionRequest, VoicePresetSelectionResponse
from app.modules.audio.services.preset_voice_service import PresetVoiceService
from app.modules.conversation.api.router import to_message_response
from app.modules.conversation.api.schemas import MessageResponse
from app.modules.conversation.repositories.models import ChatTurn, Message
from app.modules.conversation.services.account_chat import AccountChatService, chat_channel
from app.modules.conversation.services.conversation_service import ConversationService
from app.modules.identity.api.account_router import ACCESS_COOKIE, Account, DatabaseSession, Mutation, auth, setup
from app.modules.state.api.schemas import StateResponse
from app.modules.state.services.state_service import StateService, to_state_response
from app.shared.database.session import get_session_factory
from app.shared.database.companion_lock import try_companion_lock
from app.shared.exceptions.errors import AppError, ConflictError, UnauthorizedError, UnavailableError


router = APIRouter(tags=["account-chat"])
conversations = ConversationService()
states = StateService()
chat = AccountChatService()
audio = AudioManager()
voice_presets = PresetVoiceService()
MAX_SEQUENCE = 2**63 - 1


class AccountMessageResponse(MessageResponse):
    turn_id: uuid.UUID | None
    is_proactive: bool
    audio_url: str | None


class HistoryPage(BaseModel):
    messages: list[AccountMessageResponse]
    has_more: bool
    next_cursor: int | None


class SendMessageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_message_id: uuid.UUID
    message_type: Literal["text"] = "text"
    content: str = Field(min_length=1, max_length=8000)

    @field_validator("content", mode="before")
    @classmethod
    def strip_content(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class ChatTurnStatus(BaseModel):
    turn_id: uuid.UUID
    trigger_sequence: int
    status: str
    attempt: int


class SendMessageResponse(BaseModel):
    message: AccountMessageResponse
    turn_id: uuid.UUID
    status: str


class MessageAudio(BaseModel):
    message_id: uuid.UUID
    audio_url: str


@router.get("/companion/voice/health", response_model=AudioHealthResponse)
async def get_voice_health(account: Account) -> AudioHealthResponse:
    return await audio.health()


@router.get("/companion/voice/presets", response_model=list[VoicePresetResponse])
async def list_voice_presets(account: Account) -> list[VoicePresetResponse]:
    return voice_presets.list_catalog()


@router.get("/companion/voice/preset", response_model=VoicePresetSelectionResponse)
async def get_voice_preset(response: Response, account: Account, session: DatabaseSession) -> VoicePresetSelectionResponse:
    response.headers["Cache-Control"] = "no-store"
    companion = await setup.get_ready(session, account.user_id)
    return await voice_presets.get_selection(session, account.user_id, companion.id)


@router.put("/companion/voice/preset", response_model=VoicePresetSelectionResponse, dependencies=Mutation)
async def set_voice_preset(
    body: VoicePresetSelectionRequest, response: Response, account: Account, session: DatabaseSession,
) -> VoicePresetSelectionResponse:
    response.headers["Cache-Control"] = "no-store"
    companion = await setup.get_ready(session, account.user_id)
    return await voice_presets.set_selection(session, account.user_id, companion.id, body.preset_id)


def _turn_status(turn: ChatTurn) -> ChatTurnStatus:
    return ChatTurnStatus(turn_id=turn.id, trigger_sequence=turn.trigger_sequence, status=turn.status, attempt=turn.attempt)


def _message_response(message: Message) -> AccountMessageResponse:
    fields = to_message_response(message).model_dump()
    meta = message.metadata_
    asset = meta.get("audio_asset_id")
    return AccountMessageResponse(
        **fields, turn_id=meta.get("turn_id"), is_proactive=bool(meta.get("is_proactive")),
        audio_url=f"/api/chat/audio/{asset}" if asset else None,
    )


@router.get("/chat/messages", response_model=HistoryPage)
async def get_history(
    account: Account, session: DatabaseSession, response: Response,
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
    before_sequence: Annotated[int | None, Query(gt=0, le=MAX_SEQUENCE)] = None,
    after_sequence: Annotated[int | None, Query(ge=0, le=MAX_SEQUENCE)] = None,
) -> HistoryPage:
    if before_sequence is not None and after_sequence is not None:
        raise AppError("只能指定一个历史分页游标")
    response.headers["Cache-Control"] = "no-store"
    companion = await setup.get_ready(session, account.user_id)
    history, has_more = await conversations.list_managed_messages(
        session, account.user_id, companion.id, limit, before_sequence, after_sequence,
    )
    cursor = history[-1 if after_sequence is not None else 0].sequence_number if history else None
    return HistoryPage(messages=[_message_response(message) for message in history], has_more=has_more, next_cursor=cursor)


@router.get("/companion/state", response_model=StateResponse)
async def get_state(account: Account, session: DatabaseSession, response: Response) -> StateResponse:
    response.headers["Cache-Control"] = "no-store"
    companion = await setup.get_ready(session, account.user_id)
    return to_state_response(await states.get_current(session, account.user_id, companion.id))


@router.post("/chat/messages", response_model=SendMessageResponse, status_code=202, dependencies=Mutation)
async def send_message(
    body: SendMessageRequest, account: Account, session: DatabaseSession, response: Response,
) -> SendMessageResponse:
    response.headers["Cache-Control"] = "no-store"
    message, turn = await chat.send(session, account.user_id, body.client_message_id, body.content)
    return SendMessageResponse(message=_message_response(message), turn_id=turn.id, status=turn.status)


@router.post("/chat/turns/{turn_id}/retry", response_model=ChatTurnStatus, status_code=202, dependencies=Mutation)
async def retry_turn(
    turn_id: uuid.UUID, account: Account, session: DatabaseSession, response: Response,
) -> ChatTurnStatus:
    response.headers["Cache-Control"] = "no-store"
    return _turn_status(await chat.retry(session, account.user_id, turn_id))


@router.post("/chat/messages/{message_id}/audio", response_model=MessageAudio, dependencies=Mutation)
async def synthesize_message(
    message_id: uuid.UUID, account: Account, session: DatabaseSession, response: Response,
) -> MessageAudio:
    response.headers["Cache-Control"] = "no-store"
    companion = await setup.get_ready(session, account.user_id)
    async with try_companion_lock(companion.id, scope="audio") as acquired:
        if not acquired:
            raise ConflictError("正在生成语音，请稍后重试")
        result = await audio.synthesize_for_message(session, account.user_id, companion.id, message_id)
        if not result.audio_url:
            raise UnavailableError("语音生成失败，可重试")
        asset = uuid.UUID(result.audio_url.rsplit("/", 1)[-1])
        await conversations.set_message_audio(session, account.user_id, companion.id, message_id, asset)
    payload = MessageAudio(message_id=message_id, audio_url=f"/api/chat/audio/{asset}")
    try:
        async with Redis.from_url(get_settings().redis_url, socket_connect_timeout=2, socket_timeout=2) as redis:
            await redis.publish(chat_channel(companion.id), f"id: audio:{asset}\nevent: media.ready\ndata: {payload.model_dump_json()}\n\n")
    except RedisError:
        pass
    return payload


@router.get("/chat/audio/{asset_id}")
async def get_message_audio(asset_id: uuid.UUID, account: Account, session: DatabaseSession) -> FileResponse:
    companion = await setup.get_ready(session, account.user_id)
    path = await audio.resolve_asset_file(session, account.user_id, companion.id, asset_id)
    return FileResponse(path, media_type="audio/wav", headers={"Cache-Control": "private, no-store"})


@router.get("/chat/stream")
async def get_stream(
    request: Request, account: Account, session: DatabaseSession,
    after_sequence: Annotated[int | None, Query(ge=0, le=MAX_SEQUENCE)] = None,
) -> StreamingResponse:
    companion = await setup.get_ready(session, account.user_id)
    if after_sequence is None:
        recent, _ = await conversations.list_managed_messages(session, account.user_id, companion.id, 1, None, None)
        after_sequence = recent[-1].sequence_number if recent else 0

    after = after_sequence
    last_event = request.headers.get("Last-Event-ID", "")
    if last_event.startswith("message:") and last_event[8:].isascii() and last_event[8:].isdigit() and len(last_event) < 28:
        after = max(after, min(int(last_event[8:]), MAX_SEQUENCE))
    access = request.cookies[ACCESS_COOKIE]
    return StreamingResponse(
        _chat_frames(account.user_id, companion.id, after, access),
        media_type="text/event-stream", headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


async def _chat_frames(
    user_id: uuid.UUID, companion_id: uuid.UUID, sequence: int, access: str,
) -> AsyncIterator[str]:
    seen_turns: set[str] = set()
    state_version: int | None = None
    heartbeat = 0
    loop = asyncio.get_running_loop()
    factory = get_session_factory()
    async with Redis.from_url(get_settings().redis_url, decode_responses=True, socket_connect_timeout=2) as redis:
        async with redis.pubsub() as subscription:
            try:
                await subscription.subscribe(chat_channel(companion_id))
                live = True
            except RedisError:
                live = False
            while True:
                async with factory() as session:
                    try:
                        principal = await auth.authenticate(session, access)
                    except UnauthorizedError:
                        return
                    if principal.user_id != user_id:
                        return
                    messages, has_more = await conversations.list_managed_messages(
                        session, user_id, companion_id, 100, None, sequence,
                    )
                    turns = await chat.recent_turns(session, user_id, companion_id)
                    state = await states.get_current(session, user_id, companion_id)
                for message in messages:
                    sequence = message.sequence_number
                    payload = _message_response(message).model_dump_json()
                    yield f"id: message:{sequence}\nevent: message.persisted\ndata: {payload}\n\n"
                current_turns: set[str] = set()
                for turn in turns:
                    key = f"turn:{turn.id}:{turn.attempt}:{turn.status}"
                    current_turns.add(key)
                    if key not in seen_turns:
                        yield f"id: {key}\nevent: turn.status\ndata: {_turn_status(turn).model_dump_json()}\n\n"
                seen_turns = current_turns
                if state.version != state_version:
                    state_version = state.version
                    yield f"id: state:{state_version}\nevent: state.updated\ndata: {to_state_response(state).model_dump_json()}\n\n"
                if has_more:
                    continue
                heartbeat += 1
                if heartbeat % 10 == 1:
                    yield ": keepalive\n\n"
                deadline = loop.time() + 1
                while live and (remaining := deadline - loop.time()) > 0:
                    try:
                        pubsub_event = await subscription.get_message(ignore_subscribe_messages=True, timeout=remaining)
                    except RedisError:
                        live = False
                        break
                    if pubsub_event and isinstance(pubsub_event["data"], str):
                        yield pubsub_event["data"]
                if not live:
                    await asyncio.sleep(max(0, deadline - loop.time()))
