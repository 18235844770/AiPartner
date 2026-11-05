import pytest
from httpx import ASGITransport, AsyncClient
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.main import create_app
from app.shared.cors import apply_desktop_cors


@pytest.fixture
async def client() -> AsyncClient:
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http_client:
        yield http_client


async def test_health_reports_api_even_when_infrastructure_is_down(client: AsyncClient) -> None:
    response = await client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["api"] == "ok"
    assert body["status"] in {"ok", "degraded"}
    assert body["database"] in {"ok", "down"}
    assert body["redis"] in {"ok", "down"}
    assert body["pgvector"] in {"ok", "down", "unknown"}


async def test_create_user_rejects_blank_name(client: AsyncClient) -> None:
    response = await client.post("/api/users", json={"display_name": "   "})
    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"


async def test_create_message_rejects_unknown_metadata(client: AsyncClient) -> None:
    response = await client.post(
        "/api/users/00000000-0000-0000-0000-000000000001/companions/"
        "00000000-0000-0000-0000-000000000002/conversations/"
        "00000000-0000-0000-0000-000000000003/messages",
        json={"sender_type": "user", "content": "你好", "metadata": {"mood": "happy"}},
    )
    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"


def test_unhandled_error_response_includes_desktop_origin() -> None:
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/",
            "headers": [(b"origin", b"http://127.0.0.1:5173")],
            "query_string": b"",
        }
    )
    response = apply_desktop_cors(request, JSONResponse({"code": "internal_error"}))
    assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:5173"


def test_unhandled_error_response_ignores_other_origins() -> None:
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/",
            "headers": [(b"origin", b"https://example.com")],
            "query_string": b"",
        }
    )
    response = apply_desktop_cors(request, JSONResponse({"code": "internal_error"}))
    assert "access-control-allow-origin" not in response.headers
