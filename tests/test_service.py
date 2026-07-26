from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING
from typing import Any

import httpx
import pytest

from ytdl_rest import download
from ytdl_rest import service
from ytdl_rest.config import Settings
from ytdl_rest.download import Media
from ytdl_rest.service import UploadError

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path


def fake_transport(
    monkeypatch: pytest.MonkeyPatch, handler: Callable[[httpx.Request], httpx.Response]
) -> list[httpx.Request]:
    """Route the upload client at a handler instead of the network."""
    seen: list[httpx.Request] = []

    def record(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    real_client = httpx.AsyncClient

    def factory(**kwargs: Any) -> httpx.AsyncClient:
        kwargs["transport"] = httpx.MockTransport(record)
        return real_client(**kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", factory)
    return seen


async def test_upload_returns_the_public_link(
    settings: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "song.mp3"
    path.write_bytes(b"audio")
    seen = fake_transport(
        monkeypatch,
        lambda _: httpx.Response(200, json={"status": "success", "url": "http://internal:8080/ab.mp3"}),
    )

    assert await service.upload(settings, path) == "https://s.test/ab.mp3"
    assert seen[0].url == httpx.URL("http://filehost.test/api/")
    assert b"song.mp3" in seen[0].content


async def test_upload_reports_a_refusing_host(
    settings: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "song.mp3"
    path.write_bytes(b"audio")
    fake_transport(monkeypatch, lambda _: httpx.Response(413, text="File too large"))

    with pytest.raises(UploadError, match="413"):
        await service.upload(settings, path)


async def test_upload_reports_a_body_without_a_url(
    settings: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "song.mp3"
    path.write_bytes(b"audio")
    fake_transport(monkeypatch, lambda _: httpx.Response(200, json={"status": "error"}))

    with pytest.raises(UploadError, match="without a url"):
        await service.upload(settings, path)


async def test_upload_sends_configured_credentials(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(upload_url="http://filehost.test/api/", upload_basic_auth="user:secret")
    path = tmp_path / "song.mp3"
    path.write_bytes(b"audio")
    seen = fake_transport(monkeypatch, lambda _: httpx.Response(200, json={"url": "http://filehost.test/ab.mp3"}))

    await service.upload(settings, path)
    assert seen[0].headers["authorization"].startswith("Basic ")


async def test_fetch_downloads_then_publishes(
    settings: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_run(_: Settings, request: Any, outdir: Path) -> Media:
        path = outdir / "song.mp3"
        path.write_bytes(b"audio")
        return Media(path=path, title="A Song", duration=9.0, extractor="Fake", webpage_url="u")

    monkeypatch.setattr(download, "run", fake_run)
    fake_transport(monkeypatch, lambda _: httpx.Response(200, json={"url": "http://internal:8080/ab.mp3"}))

    result = await service.fetch(settings, "u", mode="audio", format="mp3")
    assert result.url == "https://s.test/ab.mp3"
    assert result.ext == "mp3"
    assert result.size_bytes == 5
    assert result.as_dict()["title"] == "A Song"


async def test_fetch_cleans_up_the_work_directory(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    leaked: list[Path] = []

    def fake_run(_: Settings, request: Any, outdir: Path) -> Media:
        leaked.append(outdir)
        path = outdir / "song.mp3"
        path.write_bytes(b"audio")
        return Media(path=path, title="t", duration=None, extractor="Fake", webpage_url="u")

    monkeypatch.setattr(download, "run", fake_run)
    fake_transport(monkeypatch, lambda _: httpx.Response(200, json={"url": "http://i/ab.mp3"}))

    await service.fetch(settings, "u", mode="audio", format="mp3")
    assert not leaked[0].exists()


async def test_fetch_gives_up_after_the_download_timeout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(work_dir=tmp_path, download_timeout_seconds=0.01)

    def slow(_: Settings, request: Any, outdir: Path) -> Media:
        import time

        time.sleep(0.5)
        raise AssertionError("should have been abandoned")

    monkeypatch.setattr(download, "run", slow)
    with pytest.raises(asyncio.TimeoutError):
        await service.fetch(settings, "u", mode="audio", format="mp3")


async def test_info_reads_metadata(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(download, "probe", lambda _, url: {"title": url})
    assert await service.info(settings, "u") == {"title": "u"}
