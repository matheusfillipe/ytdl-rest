from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from ytdl_rest import api
from ytdl_rest import service
from ytdl_rest.auth import hash_key
from ytdl_rest.config import Settings
from ytdl_rest.download import ExtractionError
from ytdl_rest.download import UnsupportedRequestError
from ytdl_rest.service import Result
from ytdl_rest.service import UploadError

RESULT = Result(
    url="https://s.test/ab.mp3",
    title="A Song",
    duration=9.0,
    size_bytes=5,
    ext="mp3",
    extractor="Fake",
    webpage_url="u",
)


def client(settings: Settings | None = None) -> TestClient:
    return TestClient(api.create_app(settings or Settings()))


def test_health_needs_no_key() -> None:
    response = client().get("/v1/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_download_returns_the_published_link(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_fetch(*_: Any, **__: Any) -> Result:
        return RESULT

    monkeypatch.setattr(service, "fetch", fake_fetch)
    response = client().post("/v1/download", json={"url": "u", "mode": "audio", "format": "mp3"})
    assert response.status_code == 200
    assert response.json()["url"] == "https://s.test/ab.mp3"


def test_download_refuses_without_the_configured_key(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_fetch(*_: Any, **__: Any) -> Result:
        return RESULT

    monkeypatch.setattr(service, "fetch", fake_fetch)
    settings = Settings(api_key_hash=hash_key("secret"))
    assert client(settings).post("/v1/download", json={"url": "u"}).status_code == 401
    accepted = client(settings).post("/v1/download", json={"url": "u"}, headers={"X-API-Key": "secret"})
    assert accepted.status_code == 200


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (UnsupportedRequestError("bad format"), 400),
        (ExtractionError("no such video"), 422),
        (UploadError("file host said no"), 502),
        (TimeoutError(), 504),
    ],
)
def test_download_maps_failures_to_status_codes(
    error: Exception, expected: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def failing(*_: Any, **__: Any) -> Result:
        raise error

    monkeypatch.setattr(service, "fetch", failing)
    assert client().post("/v1/download", json={"url": "u"}).status_code == expected


def test_info_returns_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_info(*_: Any, **__: Any) -> dict[str, Any]:
        return {"title": "A Song"}

    monkeypatch.setattr(service, "info", fake_info)
    assert client().post("/v1/info", json={"url": "u"}).json()["title"] == "A Song"


def test_info_reports_an_unreadable_url(monkeypatch: pytest.MonkeyPatch) -> None:
    async def failing(*_: Any, **__: Any) -> dict[str, Any]:
        raise ExtractionError("unsupported url")

    monkeypatch.setattr(service, "info", failing)
    assert client().post("/v1/info", json={"url": "u"}).status_code == 422


def test_mcp_is_mounted_on_the_same_app() -> None:
    assert any(getattr(route, "path", None) == "/mcp" for route in api.create_app().routes)
