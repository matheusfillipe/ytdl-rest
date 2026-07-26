"""Download, hand the file to the file host, answer with its link.

Downloads are concurrent up to a configured limit. yt-dlp is synchronous, so each one
occupies a worker thread while the event loop keeps serving other requests.
"""

from __future__ import annotations

import asyncio
import tempfile
from dataclasses import asdict
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING
from typing import Any

import httpx

from ytdl_rest import download

if TYPE_CHECKING:
    from ytdl_rest.config import Settings


class UploadError(RuntimeError):
    """The file host refused the file or could not be reached."""


@dataclass(frozen=True)
class Result:
    url: str
    title: str
    duration: float | None
    size_bytes: int
    ext: str
    extractor: str
    webpage_url: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


_limits: dict[asyncio.AbstractEventLoop, asyncio.Semaphore] = {}


def _limiter(settings: Settings) -> asyncio.Semaphore:
    """One semaphore per event loop. A semaphore outlives no loop it was created on, so
    it is keyed by the loop itself rather than by a reusable identity."""
    loop = asyncio.get_running_loop()
    if loop not in _limits:
        _limits[loop] = asyncio.Semaphore(settings.max_concurrent_downloads)
    return _limits[loop]


async def upload(settings: Settings, path: Path) -> str:
    auth: tuple[str, str] | None = None
    if settings.upload_basic_auth:
        user, _, password = settings.upload_basic_auth.partition(":")
        auth = (user, password)

    async with httpx.AsyncClient(timeout=settings.upload_timeout_seconds, auth=auth) as client:
        with path.open("rb") as handle:
            response = await client.post(settings.upload_url, files={settings.upload_field: (path.name, handle)})

    if response.status_code >= 400:
        raise UploadError(f"file host answered {response.status_code}: {response.text[:200]}")

    try:
        body = response.json()
    except ValueError as error:
        raise UploadError(f"file host answered unparseable body: {response.text[:200]}") from error

    url = body.get("url")
    if not url:
        raise UploadError(f"file host answered without a url: {body}")
    return settings.public_url(str(url))


async def fetch(
    settings: Settings,
    url: str,
    mode: str | None = None,
    quality: str | None = None,
    format: str | None = None,
) -> Result:
    """Download one item and publish it, returning the link callers should use."""
    request = download.resolve(settings, url, mode, quality, format)

    async with _limiter(settings):
        with tempfile.TemporaryDirectory(dir=settings.work_dir) as workdir:
            media = await asyncio.wait_for(
                asyncio.to_thread(download.run, settings, request, Path(workdir)),
                timeout=settings.download_timeout_seconds,
            )
            size = media.size_bytes
            link = await upload(settings, media.path)

    return Result(
        url=link,
        title=media.title,
        duration=media.duration,
        size_bytes=size,
        ext=media.path.suffix.lstrip("."),
        extractor=media.extractor,
        webpage_url=media.webpage_url,
    )


async def info(settings: Settings, url: str) -> dict[str, Any]:
    """Metadata for a URL, without downloading it."""
    return await asyncio.to_thread(download.probe, settings, url)
