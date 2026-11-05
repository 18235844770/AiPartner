import json
from collections.abc import AsyncIterator

import httpx

from app.modules.model_adapter.domain.errors import ModelAdapterError, ModelHttpError, ModelTimeoutError

_DONE = object()


class DeepSeekHttpClient:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._transport = transport

    async def complete(self, payload: dict[str, object], timeout: float) -> dict[str, object]:
        try:
            response = await self._request(payload, timeout)
        except httpx.TimeoutException as exc:
            raise ModelTimeoutError("模型调用超时") from exc
        self._raise_for_status(response)
        try:
            body = response.json()
        except json.JSONDecodeError as exc:
            raise ModelAdapterError("模型响应无法解析") from exc
        if not isinstance(body, dict):
            raise ModelAdapterError("模型响应无法解析")
        return body

    async def stream(self, payload: dict[str, object], timeout: float) -> AsyncIterator[dict[str, object]]:
        try:
            async with httpx.AsyncClient(transport=self._transport, timeout=httpx.Timeout(timeout)) as client:
                async with client.stream("POST", self._url, headers=self._headers(), json=payload) as response:
                    self._raise_for_status(response)
                    async for line in response.aiter_lines():
                        event = parse_sse_data_line(line)
                        if event is _DONE:
                            break
                        if isinstance(event, dict):
                            yield event
        except httpx.TimeoutException as exc:
            raise ModelTimeoutError("模型调用超时") from exc

    async def _request(self, payload: dict[str, object], timeout: float) -> httpx.Response:
        async with httpx.AsyncClient(transport=self._transport, timeout=httpx.Timeout(timeout)) as client:
            return await client.post(self._url, headers=self._headers(), json=payload)

    @property
    def _url(self) -> str:
        return f"{self._base_url}/chat/completions"

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._api_key}"}

    def _raise_for_status(self, response: httpx.Response) -> None:
        if response.status_code >= 400:
            raise ModelHttpError(response.status_code)


def parse_sse_data_line(line: str) -> dict[str, object] | object | None:
    if not line.startswith("data:"):
        return None
    data = line.removeprefix("data:").strip()
    if data == "[DONE]":
        return _DONE
    if not data:
        return None
    try:
        parsed = json.loads(data)
    except json.JSONDecodeError as exc:
        raise ModelAdapterError("模型响应无法解析") from exc
    if not isinstance(parsed, dict):
        raise ModelAdapterError("模型响应无法解析")
    return parsed
