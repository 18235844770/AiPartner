from typing import TypeVar

from starlette.requests import Request
from starlette.responses import Response

DESKTOP_ORIGINS = frozenset({"http://127.0.0.1:5173", "http://localhost:5173"})

ResponseT = TypeVar("ResponseT", bound=Response)


def apply_desktop_cors(request: Request, response: ResponseT) -> ResponseT:
    """未处理异常由最外层中间件直接返回，不会经过 CORS 中间件。"""
    origin = request.headers.get("origin")
    if origin in DESKTOP_ORIGINS:
        response.headers["access-control-allow-origin"] = origin
        response.headers["vary"] = "Origin"
    return response
