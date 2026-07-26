"""MCP surface, so an agent can fetch a media link as a tool call."""

from __future__ import annotations

from typing import Annotated
from typing import Any

from fastmcp import FastMCP
from pydantic import Field

from ytdl_rest import service
from ytdl_rest.auth import verify
from ytdl_rest.config import Settings
from ytdl_rest.config import get_settings

KEY_FIELD = Field(description="API key for this ytdl-rest instance.")

INSTRUCTIONS = """
ytdl-rest downloads media from any site yt-dlp supports and republishes it on a file host,
answering with a link anyone can open.

Links are temporary: the host deletes files after its own retention window, so pass the
link on promptly rather than storing it.
""".strip()


class NotAuthorizedError(RuntimeError):
    """The supplied key does not match."""


def create_mcp(settings: Settings | None = None) -> FastMCP:
    resolved = settings or get_settings()
    mcp: FastMCP = FastMCP(name="ytdl-rest", instructions=INSTRUCTIONS)

    def _check(api_key: str | None) -> None:
        # Clients reaching MCP over HTTP send headers, but stdio clients have none, so the
        # key is also accepted as a tool argument.
        if not verify(api_key, resolved.api_key_hash):
            raise NotAuthorizedError("invalid or missing api_key")

    @mcp.tool
    async def download_media(
        url: Annotated[str, Field(description="Page or media URL to download, from any site yt-dlp supports.")],
        mode: Annotated[str | None, Field(description="'video' or 'audio'. Audio extracts the soundtrack.")] = None,
        quality: Annotated[
            str | None,
            Field(
                description="Video: 'best', 'worst' or a height such as '1080'. Audio: 'best' or kbps such as '192'."
            ),
        ] = None,
        format: Annotated[
            str | None,
            Field(description="Video container (mp4, mkv, webm) or audio codec (mp3, m4a, opus, flac, wav)."),
        ] = None,
        api_key: Annotated[str | None, KEY_FIELD] = None,
    ) -> dict[str, Any]:
        """Download media and publish it, returning a temporary public link.

        The call runs until the download finishes, which for a long video is minutes.
        Oversized or over-long media is refused rather than truncated.
        """
        _check(api_key)
        result = await service.fetch(resolved, url=url, mode=mode, quality=quality, format=format)
        return result.as_dict()

    @mcp.tool
    async def media_info(
        url: Annotated[str, Field(description="Page or media URL to inspect.")],
        api_key: Annotated[str | None, KEY_FIELD] = None,
    ) -> dict[str, Any]:
        """Title, duration and available formats for a URL, without downloading it."""
        _check(api_key)
        return await service.info(resolved, url)

    return mcp
