import uuid

from fastapi import APIRouter, Depends, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.infrastructure.api.schemas import (
    AddModelConfigVersionRequest,
    BackgroundTaskResponse,
    CreateBackgroundTaskRequest,
    CreateModelConfigRequest,
    ModelCallLogResponse,
    ModelCallSnapshotResponse,
    ModelConfigResponse,
    RecordModelCallRequest,
    RollbackModelConfigRequest,
    TaskTransitionRequest,
)
from app.modules.infrastructure.domain.enums import ModelConfigKey
from app.modules.infrastructure.services.background_task_service import BackgroundTaskService, to_task_response
from app.modules.infrastructure.services.model_call_log_service import (
    ModelCallLogService,
    to_log_response,
    to_snapshot_response,
)
from app.modules.infrastructure.services.model_config_service import ModelConfigService, to_config_response
from app.shared.database.session import get_session

config_router = APIRouter(prefix="/model-configs", tags=["infrastructure"])
log_router = APIRouter(prefix="/model-call-logs", tags=["infrastructure"])
task_router = APIRouter(prefix="/background-tasks", tags=["infrastructure"])
scope_router = APIRouter(
    prefix="/users/{user_id}/companions/{companion_id}",
    tags=["infrastructure"],
)

config_service = ModelConfigService()
log_service = ModelCallLogService()
task_service = BackgroundTaskService()


@config_router.post("", response_model=ModelConfigResponse, status_code=201)
async def create_model_config(
    body: CreateModelConfigRequest,
    session: AsyncSession = Depends(get_session),
) -> ModelConfigResponse:
    config = await config_service.create(session, body)
    return to_config_response(config)


@config_router.get("", response_model=list[ModelConfigResponse])
async def list_model_configs(session: AsyncSession = Depends(get_session)) -> list[ModelConfigResponse]:
    configs = await config_service.list_configs(session)
    return [to_config_response(config) for config in configs]


@config_router.post("/{config_key}/versions", response_model=ModelConfigResponse, status_code=201)
async def add_model_config_version(
    config_key: ModelConfigKey,
    body: AddModelConfigVersionRequest,
    session: AsyncSession = Depends(get_session),
) -> ModelConfigResponse:
    config = await config_service.add_version(session, config_key, body)
    return to_config_response(config)


@config_router.post("/{config_key}/rollback", response_model=ModelConfigResponse)
async def rollback_model_config(
    config_key: ModelConfigKey,
    body: RollbackModelConfigRequest,
    session: AsyncSession = Depends(get_session),
) -> ModelConfigResponse:
    config = await config_service.rollback(session, config_key, body)
    return to_config_response(config)


@log_router.post("", response_model=ModelCallLogResponse, status_code=201)
async def record_model_call(
    body: RecordModelCallRequest,
    session: AsyncSession = Depends(get_session),
) -> ModelCallLogResponse:
    log = await log_service.record(session, body)
    return to_log_response(log)


@log_router.get("", response_model=list[ModelCallLogResponse])
async def list_model_calls(
    trace_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> list[ModelCallLogResponse]:
    logs = await log_service.list_by_trace(session, trace_id)
    return [to_log_response(log) for log in logs]


@scope_router.get("/model-call-logs/{log_id}", response_model=ModelCallSnapshotResponse)
async def get_companion_model_call_snapshot(
    user_id: uuid.UUID,
    companion_id: uuid.UUID,
    log_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> ModelCallSnapshotResponse:
    log = await log_service.get_snapshot(session, user_id, companion_id, log_id)
    return to_snapshot_response(log)


@scope_router.get("/model-call-logs", response_model=list[ModelCallLogResponse])
async def list_companion_model_calls(
    user_id: uuid.UUID,
    companion_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> list[ModelCallLogResponse]:
    logs = await log_service.list_for_companion(session, user_id, companion_id)
    return [to_log_response(log) for log in logs]


@scope_router.get("/background-tasks", response_model=list[BackgroundTaskResponse])
async def list_companion_background_tasks(
    user_id: uuid.UUID,
    companion_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> list[BackgroundTaskResponse]:
    tasks = await task_service.list_for_companion(session, user_id, companion_id)
    return [to_task_response(task) for task in tasks]


@task_router.post("", response_model=BackgroundTaskResponse)
async def create_background_task(
    body: CreateBackgroundTaskRequest,
    response: Response,
    session: AsyncSession = Depends(get_session),
) -> BackgroundTaskResponse:
    result = await task_service.create(session, body)
    response.status_code = 201 if result.created else 200
    return to_task_response(result.task)


@task_router.get("/{task_id}", response_model=BackgroundTaskResponse)
async def get_background_task(
    task_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> BackgroundTaskResponse:
    task = await task_service.get(session, task_id)
    return to_task_response(task)


@task_router.post("/{task_id}/transitions", response_model=BackgroundTaskResponse)
async def transition_background_task(
    task_id: uuid.UUID,
    body: TaskTransitionRequest,
    session: AsyncSession = Depends(get_session),
) -> BackgroundTaskResponse:
    task = await task_service.transition(session, task_id, body)
    return to_task_response(task)
