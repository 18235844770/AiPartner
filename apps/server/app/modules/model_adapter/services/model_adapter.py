import logging
import time
import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime
from typing import TypeVar

from pydantic import BaseModel, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import Settings, get_settings
from app.modules.infrastructure.api.schemas import RecordModelCallRequest
from app.modules.infrastructure.domain.enums import CONFIG_TASK_TYPES, ModelCallStatus, ModelConfigKey, ModelProvider
from app.modules.infrastructure.repositories.infrastructure_repository import ModelConfigRepository
from app.modules.infrastructure.services.model_call_log_service import ModelCallLogService
from app.modules.model_adapter.domain.errors import (
    ModelAdapterError,
    ModelCapabilityError,
    ModelHttpError,
    ModelOutputError,
    ModelTimeoutError,
)
from app.modules.model_adapter.domain.messages import ChatMessage, TextCompletion, build_chat_payload
from app.modules.model_adapter.services.deepseek_client import DeepSeekHttpClient
from app.shared.database.session import get_session_factory
from app.shared.exceptions.errors import NotFoundError

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)
_RETRYABLE_HTTP = {429, 500, 502, 503, 504}
_CHAT_TASKS = {ModelConfigKey.CONVERSATION, ModelConfigKey.DECISION, ModelConfigKey.MEMORY}


class ModelCallScope(BaseModel):
    trace_id: uuid.UUID
    user_id: uuid.UUID | None = None
    companion_id: uuid.UUID | None = None
    conversation_id: uuid.UUID | None = None
    dialogue_decision_id: uuid.UUID | None = None
    background_task_id: uuid.UUID | None = None


class ModelAdapter:
    def __init__(
        self,
        client: DeepSeekHttpClient | None = None,
        settings: Settings | None = None,
        configs: ModelConfigRepository | None = None,
        logs: ModelCallLogService | None = None,
        session_factory: Callable[[], AbstractAsyncContextManager[AsyncSession]] | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._client = client or DeepSeekHttpClient(
            base_url=self._settings.deepseek_base_url,
            api_key=self._settings.deepseek_api_key,
        )
        self._configs = configs or ModelConfigRepository()
        self._logs = logs or ModelCallLogService()
        self._session_factory = session_factory or get_session_factory()

    async def complete_text(
        self,
        task: ModelConfigKey,
        messages: list[ChatMessage],
        scope: ModelCallScope,
        *,
        json_object: bool = False,
    ) -> TextCompletion:
        self._require_chat_task(task)
        config = await self._load_config(task)
        self._require_api_key()
        payload = build_chat_payload(
            config.model_name,
            messages,
            config.parameters,
            json_object=json_object,
            stream=False,
        )
        body = await self._complete_with_retry(payload, config, task, scope)
        content, finish_reason, input_tokens, output_tokens = _read_completion(body)
        return TextCompletion(
            content=content,
            model_name=str(body.get("model") or config.model_name),
            finish_reason=finish_reason,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )

    async def complete_structured(
        self,
        task: ModelConfigKey,
        messages: list[ChatMessage],
        result_type: type[T],
        scope: ModelCallScope,
    ) -> T:
        completion = await self.complete_text(task, messages, scope, json_object=True)
        try:
            return result_type.model_validate_json(completion.content)
        except ValidationError as exc:
            raise ModelOutputError("模型输出不符合结构") from exc

    async def stream_text(
        self,
        task: ModelConfigKey,
        messages: list[ChatMessage],
        scope: ModelCallScope,
    ) -> AsyncIterator[str]:
        self._require_chat_task(task)
        config = await self._load_config(task)
        self._require_api_key()
        payload = build_chat_payload(config.model_name, messages, config.parameters, json_object=False, stream=True)
        started = time.perf_counter()
        created_at = datetime.now(UTC)
        input_tokens: int | None = None
        output_tokens: int | None = None
        produced = False
        try:
            async for chunk in self._client.stream(payload, self._settings.deepseek_timeout_seconds):
                usage = chunk.get("usage")
                if isinstance(usage, dict):
                    input_tokens = _optional_int(usage.get("prompt_tokens"))
                    output_tokens = _optional_int(usage.get("completion_tokens"))
                piece = _stream_piece(chunk)
                if piece:
                    produced = True
                    yield piece
        except GeneratorExit:
            await self._log(
                config,
                task,
                scope,
                status=ModelCallStatus.CANCELLED,
                latency_ms=_latency(started),
                error_code="cancelled",
                error_message="调用已取消",
                created_at=created_at,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
            )
            raise
        except (ModelTimeoutError, ModelHttpError, ModelAdapterError) as exc:
            await self._log_exception(config, task, scope, exc, started, created_at)
            raise
        if not produced:
            await self._log(
                config,
                task,
                scope,
                status=ModelCallStatus.FAILED,
                latency_ms=_latency(started),
                error_code="empty_content",
                error_message="模型没有返回文本",
                created_at=created_at,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
            )
            raise ModelOutputError("模型没有返回文本")
        await self._log(
            config,
            task,
            scope,
            status=ModelCallStatus.SUCCESS,
            latency_ms=_latency(started),
            created_at=created_at,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )

    async def embed(self, task: ModelConfigKey, scope: ModelCallScope) -> None:
        del task, scope
        raise ModelCapabilityError("DeepSeek 官方接口没有 Embedding，不能生成向量")

    async def _complete_with_retry(
        self,
        payload: dict[str, object],
        config: object,
        task: ModelConfigKey,
        scope: ModelCallScope,
    ) -> dict[str, object]:
        attempts = self._settings.deepseek_max_retries + 1
        last_error: ModelAdapterError | None = None
        for attempt in range(attempts):
            started = time.perf_counter()
            created_at = datetime.now(UTC)
            try:
                body = await self._client.complete(payload, self._settings.deepseek_timeout_seconds)
            except (ModelTimeoutError, ModelHttpError) as exc:
                retryable = isinstance(exc, ModelTimeoutError) or (
                    isinstance(exc, ModelHttpError) and exc.http_status in _RETRYABLE_HTTP
                )
                await self._log_exception(config, task, scope, exc, started, created_at)
                last_error = exc
                if retryable and attempt < attempts - 1:
                    continue
                raise
            content, _, input_tokens, output_tokens = _read_completion(body)
            if not content.strip():
                await self._log(
                    config,
                    task,
                    scope,
                    status=ModelCallStatus.FAILED,
                    latency_ms=_latency(started),
                    error_code="empty_content",
                    error_message="模型没有返回文本",
                    created_at=created_at,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                )
                raise ModelOutputError("模型没有返回文本")
            await self._log(
                config,
                task,
                scope,
                status=ModelCallStatus.SUCCESS,
                latency_ms=_latency(started),
                created_at=created_at,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
            )
            return body
        if last_error is not None:
            raise last_error
        raise ModelAdapterError("模型服务不可用")

    def _require_chat_task(self, task: ModelConfigKey) -> None:
        if task not in _CHAT_TASKS:
            raise ModelCapabilityError("这个任务不使用文本生成")

    def _require_api_key(self) -> None:
        if self._settings.deepseek_api_key.strip():
            return
        raise ModelAdapterError("未配置 DeepSeek API Key")

    async def _load_config(self, task: ModelConfigKey) -> object:
        async with self._session_factory() as session:
            async with session.begin():
                config = await self._configs.get_default(session, CONFIG_TASK_TYPES[task].value)
        if config is None:
            raise NotFoundError("模型配置不存在")
        return config

    async def _log_exception(
        self,
        config: object,
        task: ModelConfigKey,
        scope: ModelCallScope,
        exc: ModelAdapterError,
        started: float,
        created_at: datetime,
    ) -> None:
        if isinstance(exc, ModelTimeoutError):
            status = ModelCallStatus.TIMEOUT
            error_code = "timeout"
            error_message = "模型调用超时"
        elif isinstance(exc, ModelHttpError):
            status = ModelCallStatus.FAILED
            error_code = f"http_{exc.http_status}"
            error_message = "模型服务不可用"
        else:
            status = ModelCallStatus.FAILED
            error_code = exc.code
            error_message = exc.message
        await self._log(
            config,
            task,
            scope,
            status=status,
            latency_ms=_latency(started),
            error_code=error_code,
            error_message=error_message,
            created_at=created_at,
        )

    async def _log(
        self,
        config: object,
        task: ModelConfigKey,
        scope: ModelCallScope,
        *,
        status: ModelCallStatus,
        latency_ms: int,
        created_at: datetime | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
    ) -> None:
        started_at = created_at or datetime.now(UTC)
        completed_at = datetime.now(UTC)
        if completed_at < started_at:
            completed_at = started_at
        request = RecordModelCallRequest(
            user_id=scope.user_id,
            companion_id=scope.companion_id,
            conversation_id=scope.conversation_id,
            dialogue_decision_id=scope.dialogue_decision_id,
            background_task_id=scope.background_task_id,
            config_id=_config_attr(config, "id"),
            trace_id=scope.trace_id,
            task_type=CONFIG_TASK_TYPES[task],
            provider=ModelProvider.DEEPSEEK,
            model_name=str(_config_attr(config, "model_name")),
            status=status,
            latency_ms=latency_ms,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            error_code=error_code,
            error_message=error_message,
            created_at=started_at,
            completed_at=completed_at,
        )
        async with self._session_factory() as session:
            await self._logs.record(session, request)
        logger.info("model call task=%s status=%s latency_ms=%s", task.value, status.value, latency_ms)


def _read_completion(body: dict[str, object]) -> tuple[str, str | None, int | None, int | None]:
    choices = body.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        return "", None, *_usage(body)
    message = choices[0].get("message")
    content = ""
    if isinstance(message, dict) and isinstance(message.get("content"), str):
        content = message["content"]
    finish_reason = choices[0].get("finish_reason")
    reason = finish_reason if isinstance(finish_reason, str) else None
    return content, reason, *_usage(body)


def _usage(body: dict[str, object]) -> tuple[int | None, int | None]:
    usage = body.get("usage")
    if not isinstance(usage, dict):
        return None, None
    return _optional_int(usage.get("prompt_tokens")), _optional_int(usage.get("completion_tokens"))


def _stream_piece(chunk: dict[str, object]) -> str:
    choices = chunk.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        return ""
    delta = choices[0].get("delta")
    if not isinstance(delta, dict):
        return ""
    content = delta.get("content")
    return content if isinstance(content, str) else ""


def _optional_int(value: object) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return None


def _latency(started: float) -> int:
    return max(0, int((time.perf_counter() - started) * 1000))


def _config_attr(config: object, name: str) -> object:
    return getattr(config, name)
