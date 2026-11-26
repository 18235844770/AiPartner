from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Request, Response
from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import get_settings
from app.modules.identity.api.account_schemas import (
    AccountResponse, ChangePasswordRequest, DeleteAccountRequest, LoginRequest, ManagedCompanionResponse,
    RegisterRequest, UpdateProfileRequest,
)
from app.modules.identity.repositories.models import Companion
from app.modules.identity.services.auth_service import AccountPrincipal, AuthService, SessionTokens
from app.modules.identity.services.companion_setup import CompanionSetupService
from app.shared.database.session import get_session
from app.shared.exceptions.errors import ForbiddenError, RateLimitError, UnauthorizedError, UnavailableError


router = APIRouter(tags=["account"])
auth = AuthService()
setup = CompanionSetupService()
ACCESS_COOKIE = "__Host-companion-access"
REFRESH_COOKIE = "__Host-companion-refresh"
DatabaseSession = Annotated[AsyncSession, Depends(get_session)]


def require_same_origin(request: Request) -> None:
    if request.headers.get("X-Companion-Request") != "1" or request.headers.get("Sec-Fetch-Site") in {
        "cross-site", "same-site",
    }:
        raise ForbiddenError("请求来源无效")


async def limit_authentication(request: Request, action: str, limit: int) -> None:
    host = request.client.host if request.client else "unknown"
    try:
        async with Redis.from_url(get_settings().redis_url, socket_timeout=2, socket_connect_timeout=2) as redis:
            count = await redis.eval(
                "local n = redis.call('INCR', KEYS[1]); "
                "if n == 1 then redis.call('EXPIRE', KEYS[1], 60) end; return n",
                1, f"companion:account-limit:{action}:{host}",
            )
    except RedisError as exc:
        raise UnavailableError("认证暂时不可用") from exc
    if count > limit:
        raise RateLimitError("请求过于频繁，请稍后再试")


async def current_account(request: Request, session: DatabaseSession) -> AccountPrincipal:
    access = request.cookies.get(ACCESS_COOKIE)
    if not access:
        raise UnauthorizedError("请先登录")
    return await auth.authenticate(session, access)


Account = Annotated[AccountPrincipal, Depends(current_account)]
Mutation = [Depends(require_same_origin)]


def _write_tokens(response: Response, tokens: SessionTokens) -> None:
    now = datetime.now(UTC)
    response.headers["Cache-Control"] = "no-store"
    for key, value, expiry in (
        (ACCESS_COOKIE, tokens.access, tokens.access_expires_at),
        (REFRESH_COOKIE, tokens.refresh, tokens.expires_at),
    ):
        response.set_cookie(
            key, value, max_age=max(0, int((expiry - now).total_seconds())),
            secure=True, httponly=True, samesite="strict", path="/",
        )


def _clear_tokens(response: Response) -> Response:
    response.headers["Cache-Control"] = "no-store"
    for key in (ACCESS_COOKIE, REFRESH_COOKIE):
        response.delete_cookie(key, secure=True, httponly=True, samesite="strict")
    return response


@router.post("/auth/register", status_code=202, dependencies=Mutation)
async def register(body: RegisterRequest, request: Request, session: DatabaseSession, tasks: BackgroundTasks) -> Response:
    await limit_authentication(request, "register", 5)
    user_id = await auth.register(
        session, body.username, body.password.get_secret_value(), body.display_name or body.username, body.timezone,
    )
    if user_id is not None:
        tasks.add_task(setup.initialize, user_id)
    return Response(status_code=202, headers={"Cache-Control": "no-store"})


@router.post("/auth/login", status_code=204, dependencies=Mutation)
async def login(body: LoginRequest, request: Request, session: DatabaseSession) -> Response:
    await limit_authentication(request, "login", 15)
    tokens = await auth.login(session, body.username, body.password.get_secret_value())
    response = Response(status_code=204)
    _write_tokens(response, tokens)
    return response


@router.post("/auth/refresh", status_code=204, dependencies=Mutation)
async def refresh(request: Request, session: DatabaseSession) -> Response:
    refresh_token = request.cookies.get(REFRESH_COOKIE)
    if not refresh_token:
        raise UnauthorizedError("请先登录")
    tokens = await auth.refresh(session, refresh_token)
    response = Response(status_code=204)
    _write_tokens(response, tokens)
    return response


@router.post("/auth/logout", status_code=204, dependencies=Mutation)
async def logout(request: Request, session: DatabaseSession) -> Response:
    await auth.logout(session, request.cookies.get(ACCESS_COOKIE), request.cookies.get(REFRESH_COOKIE))
    return _clear_tokens(Response(status_code=204))


@router.get("/user/me", response_model=AccountResponse)
async def get_profile(response: Response, account: Account, session: DatabaseSession) -> AccountResponse:
    response.headers["Cache-Control"] = "no-store"
    return AccountResponse.model_validate(await auth.get_user(session, account))


@router.patch("/user/me", response_model=AccountResponse, dependencies=Mutation)
async def patch_profile(
    body: UpdateProfileRequest, response: Response, account: Account, session: DatabaseSession,
) -> AccountResponse:
    response.headers["Cache-Control"] = "no-store"
    return AccountResponse.model_validate(await auth.update_profile(session, account, body.model_dump(exclude_unset=True)))


@router.post("/user/password", status_code=204, dependencies=Mutation)
async def change_password(body: ChangePasswordRequest, request: Request, account: Account, session: DatabaseSession) -> Response:
    await limit_authentication(request, "password", 10)
    await auth.change_password(
        session, account, body.current_password.get_secret_value(), body.new_password.get_secret_value(),
    )
    return Response(status_code=204, headers={"Cache-Control": "no-store"})


@router.delete("/user/me", status_code=202, dependencies=Mutation)
async def delete_account(body: DeleteAccountRequest, request: Request, account: Account, session: DatabaseSession) -> Response:
    await limit_authentication(request, "delete", 5)
    await auth.request_deletion(session, account, body.password.get_secret_value())
    return _clear_tokens(Response(status_code=202))


@router.get("/companion/me", response_model=ManagedCompanionResponse)
async def get_companion(response: Response, account: Account, session: DatabaseSession) -> ManagedCompanionResponse:
    response.headers["Cache-Control"] = "no-store"
    companion: Companion = await setup.get(session, account.user_id)
    return ManagedCompanionResponse(
        id=companion.id, name=companion.name, initialization_status=companion.initialization_status or "pending",
        initialized_at=companion.initialized_at,
    )


@router.post("/companion/me/retry", status_code=202, dependencies=Mutation)
async def retry_companion(request: Request, account: Account, tasks: BackgroundTasks) -> Response:
    await limit_authentication(request, "companion-retry", 15)
    tasks.add_task(setup.initialize, account.user_id)
    return Response(status_code=202, headers={"Cache-Control": "no-store"})
