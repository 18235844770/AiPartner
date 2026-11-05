import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError

from app.shared.cors import apply_desktop_cors
from app.shared.exceptions.errors import AppError

logger = logging.getLogger(__name__)


def _safe_validation_errors(exc: RequestValidationError) -> list[dict[str, object]]:
    safe_errors: list[dict[str, object]] = []
    for error in exc.errors():
        item = {key: _safe_value(value) for key, value in error.items()}
        safe_errors.append(item)
    return safe_errors


def _safe_value(value: object) -> object:
    if isinstance(value, dict):
        return {str(key): _safe_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_safe_value(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def handle_app_error(_request: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"code": exc.code, "message": exc.message},
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(_request: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "code": "validation_error",
                "message": "请求参数无效",
                "detail": {"errors": _safe_validation_errors(exc)},
            },
        )

    @app.exception_handler(IntegrityError)
    async def handle_integrity_error(_request: Request, exc: IntegrityError) -> JSONResponse:
        logger.warning("database integrity conflict: %s", exc.orig)
        return JSONResponse(
            status_code=409,
            content={"code": "conflict", "message": "数据约束冲突"},
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled error: %s", exc)
        response = JSONResponse(
            status_code=500,
            content={"code": "internal_error", "message": "服务器内部错误"},
        )
        return apply_desktop_cors(request, response)
