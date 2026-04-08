import asyncio

import helpers


class FakeResponse:
    def __init__(
        self, status_code: int, text: str = "", json_payload=None, json_error=False
    ):
        self.status_code = status_code
        self.text = text
        self._json_payload = json_payload
        self._json_error = json_error

    def json(self):
        if self._json_error:
            raise ValueError("json parse failed")
        return self._json_payload


def _patch_async_client(monkeypatch, response):
    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def request(self, **kwargs):
            return response

    monkeypatch.setattr(helpers.httpx, "AsyncClient", FakeAsyncClient, raising=True)


def test_palette_api_request_returns_response_for_allowed_status(monkeypatch):
    response = FakeResponse(status_code=404, text="not found")
    _patch_async_client(monkeypatch, response)

    got = asyncio.run(
        helpers.palette_api_request(
            palette_host="api.spectrocloud.com",
            method="GET",
            path="/v1/example",
            headers={"apiKey": "k"},
            allowed_status_codes={404},
        )
    )
    assert got is response


def test_palette_api_request_raises_validation_error_for_422(monkeypatch):
    response = FakeResponse(status_code=422, json_payload={"field": "invalid"})
    _patch_async_client(monkeypatch, response)

    with_exception = None
    try:
        asyncio.run(
            helpers.palette_api_request(
                palette_host="api.spectrocloud.com",
                method="POST",
                path="/v1/example",
                headers={"apiKey": "k"},
                body={"x": 1},
            )
        )
    except Exception as exc:
        with_exception = exc

    assert with_exception is not None
    assert "Validation error (422)" in str(with_exception)


def test_palette_api_request_raises_rate_limit_error_for_429(monkeypatch):
    response = FakeResponse(status_code=429, text="slow down")
    _patch_async_client(monkeypatch, response)

    with_exception = None
    try:
        asyncio.run(
            helpers.palette_api_request(
                palette_host="api.spectrocloud.com",
                method="GET",
                path="/v1/example",
                headers={"apiKey": "k"},
            )
        )
    except Exception as exc:
        with_exception = exc

    assert with_exception is not None
    assert "Rate limit error (429)" in str(with_exception)


def test_palette_api_request_raises_edgehost_not_registered_message(monkeypatch):
    response = FakeResponse(
        status_code=400,
        text="bad request",
        json_payload={
            "code": "EdgeHostDeviceNotRegistered",
            "message": "Device not registered yet",
        },
    )
    _patch_async_client(monkeypatch, response)

    with_exception = None
    try:
        asyncio.run(
            helpers.palette_api_request(
                palette_host="api.spectrocloud.com",
                method="PATCH",
                path="/v1/edgehosts/uid/meta",
                headers={"apiKey": "k"},
            )
        )
    except Exception as exc:
        with_exception = exc

    assert with_exception is not None
    assert "Edge host is not registered" in str(with_exception)
    assert "Device not registered yet" in str(with_exception)


def test_palette_api_request_raises_generic_error_for_http_failure(monkeypatch):
    response = FakeResponse(status_code=500, text="server exploded", json_error=True)
    _patch_async_client(monkeypatch, response)

    with_exception = None
    try:
        asyncio.run(
            helpers.palette_api_request(
                palette_host="api.spectrocloud.com",
                method="GET",
                path="/v1/example",
                headers={"apiKey": "k"},
            )
        )
    except Exception as exc:
        with_exception = exc

    assert with_exception is not None
    assert "API request failed with status 500" in str(with_exception)
