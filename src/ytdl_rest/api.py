"""The REST surface. One request downloads one thing and answers with its link."""

from __future__ import annotations

import shutil
from typing import Annotated
from typing import Any
from typing import Literal
from urllib.parse import quote

from fastapi import Depends
from fastapi import FastAPI
from fastapi import Header
from fastapi import HTTPException
from fastapi import status
from fastapi.responses import FileResponse
from pydantic import BaseModel
from pydantic import Field
from starlette.background import BackgroundTask

from ytdl_rest import __version__
from ytdl_rest import service
from ytdl_rest.auth import verify
from ytdl_rest.config import Settings
from ytdl_rest.config import get_settings
from ytdl_rest.download import ExtractionError
from ytdl_rest.download import UnsupportedRequestError
from ytdl_rest.mcp import create_mcp
from ytdl_rest.service import UploadError


class Health(BaseModel):
    status: Literal["ok"]
    version: str


class DownloadRequest(BaseModel):
    url: str = Field(description="Page or media URL, from any site yt-dlp supports.")
    mode: str | None = Field(default=None, description="'video' or 'audio'.")
    quality: str | None = Field(default=None, description="'best', 'worst', a height such as '1080', or kbps.")
    format: str | None = Field(default=None, description="Container for video, codec for audio.")


class DownloadResponse(BaseModel):
    url: str
    title: str
    duration: float | None
    size_bytes: int
    ext: str
    extractor: str
    webpage_url: str


class InfoRequest(BaseModel):
    url: str = Field(description="Page or media URL to inspect.")


def require_api_key(
    settings: Annotated[Settings, Depends(get_settings)],
    x_api_key: Annotated[str | None, Header()] = None,
) -> None:
    """No-op until a key hash is configured, so local runs need no credentials."""
    if not verify(x_api_key, settings.api_key_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid or missing X-API-Key")


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved = settings or get_settings()

    # The MCP app manages a task group in its lifespan, so the parent app has to run it;
    # mounting alone leaves it uninitialised and every call fails at request time.
    mcp_app = create_mcp(resolved).http_app(path="/")

    app = FastAPI(
        lifespan=mcp_app.lifespan,
        title="ytdl-rest",
        version=__version__,
        summary="Download media with yt-dlp and get back a temporary public link.",
        description=(
            "Point it at any URL yt-dlp supports. The media is downloaded at the requested "
            "quality, converted when audio is asked for, and published to a file host that "
            "deletes it again after its retention window."
        ),
    )

    # Depends(get_settings) would otherwise read the process-wide cached settings,
    # ignoring whatever this app was constructed with.
    app.dependency_overrides[get_settings] = lambda: resolved

    @app.get("/v1/health", response_model=Health, tags=["service"])
    def health() -> Health:
        return Health(status="ok", version=__version__)

    @app.post(
        "/v1/download",
        response_model=DownloadResponse,
        dependencies=[Depends(require_api_key)],
        tags=["media"],
    )
    async def download_media(request: DownloadRequest) -> DownloadResponse:
        """Download media and publish it. The request stays open until the file is up."""
        try:
            result = await service.fetch(
                resolved,
                url=request.url,
                mode=request.mode,
                quality=request.quality,
                format=request.format,
            )
        except UnsupportedRequestError as error:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(error)) from error
        except ExtractionError as error:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error)) from error
        except UploadError as error:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(error)) from error
        except TimeoutError as error:
            raise HTTPException(status.HTTP_504_GATEWAY_TIMEOUT, "download timed out") from error
        return DownloadResponse(**result.as_dict())

    @app.post(
        "/v1/file",
        response_class=FileResponse,
        dependencies=[Depends(require_api_key)],
        tags=["media"],
    )
    async def download_file(request: DownloadRequest) -> FileResponse:
        """Download media and answer with the file itself, so the caller keeps it private.

        The title, duration and page come back as `X-Media-Title` (URL-encoded),
        `X-Media-Duration` (seconds, empty when unknown) and `X-Media-Webpage-Url`.
        """
        try:
            downloaded = await service.download_to_disk(
                resolved,
                url=request.url,
                mode=request.mode,
                quality=request.quality,
                format=request.format,
            )
        except UnsupportedRequestError as error:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(error)) from error
        except ExtractionError as error:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error)) from error
        except TimeoutError as error:
            raise HTTPException(status.HTTP_504_GATEWAY_TIMEOUT, "download timed out") from error
        media = downloaded.media
        return FileResponse(
            media.path,
            filename=media.path.name,
            headers={
                "X-Media-Title": quote(media.title),
                "X-Media-Duration": "" if media.duration is None else str(media.duration),
                "X-Media-Webpage-Url": quote(media.webpage_url, safe=":/?&=%#"),
            },
            background=BackgroundTask(shutil.rmtree, downloaded.workdir, ignore_errors=True),
        )

    @app.post("/v1/info", dependencies=[Depends(require_api_key)], tags=["media"])
    async def media_info(request: InfoRequest) -> dict[str, Any]:
        """Title, duration and available formats, without downloading anything."""
        try:
            return await service.info(resolved, request.url)
        except ExtractionError as error:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error)) from error

    app.mount("/mcp", mcp_app)
    return app


app = create_app()
