from __future__ import annotations

from typing import Any

import pytest

from ytdl_rest import mcp as mcp_module
from ytdl_rest import service
from ytdl_rest.auth import hash_key
from ytdl_rest.config import Settings
from ytdl_rest.mcp import create_mcp
from ytdl_rest.service import Result

RESULT = Result(
    url="https://s.test/ab.mp3",
    title="A Song",
    duration=9.0,
    size_bytes=5,
    ext="mp3",
    extractor="Fake",
    webpage_url="u",
)


async def test_tools_are_exposed() -> None:
    tools = await create_mcp(Settings()).list_tools()
    assert {"download_media", "media_info"} <= {tool.name for tool in tools}


async def test_download_media_returns_the_link(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_fetch(*_: Any, **__: Any) -> Result:
        return RESULT

    monkeypatch.setattr(service, "fetch", fake_fetch)
    result = await create_mcp(Settings()).call_tool("download_media", {"url": "u", "mode": "audio"})
    assert result.structured_content == RESULT.as_dict()


async def test_media_info_returns_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_info(*_: Any, **__: Any) -> dict[str, Any]:
        return {"title": "A Song"}

    monkeypatch.setattr(service, "info", fake_info)
    result = await create_mcp(Settings()).call_tool("media_info", {"url": "u"})
    assert result.structured_content == {"title": "A Song"}


async def test_tools_refuse_a_wrong_key() -> None:
    mcp = create_mcp(Settings(api_key_hash=hash_key("secret")))
    with pytest.raises(Exception, match="api_key"):
        await mcp.call_tool("download_media", {"url": "u", "api_key": "wrong"})


def test_instructions_mention_the_link_is_temporary() -> None:
    assert "temporary" in mcp_module.INSTRUCTIONS.lower()
