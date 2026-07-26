from __future__ import annotations

from typing import TYPE_CHECKING

from ytdl_rest.config import Settings
from ytdl_rest.config import get_settings

if TYPE_CHECKING:
    import pytest


def test_settings_read_the_prefixed_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("YTDL_MAX_FILE_BYTES", "123")
    monkeypatch.setenv("YTDL_UPLOAD_URL", "http://host/api/")
    get_settings.cache_clear()
    try:
        settings = get_settings()
    finally:
        get_settings.cache_clear()
    assert settings.max_file_bytes == 123
    assert settings.upload_url == "http://host/api/"


def test_extra_options_accept_json_from_the_environment() -> None:
    assert Settings(extra_options='{"retries": 9}').extra_options == {"retries": 9}
    assert Settings(extra_options="").extra_options == {}


def test_public_url_rewrites_the_host_reported_link() -> None:
    settings = Settings(upload_public_base="https://s.test/")
    assert settings.public_url("http://internal:8080/ab.mp3") == "https://s.test/ab.mp3"


def test_public_url_is_left_alone_when_no_base_is_configured() -> None:
    assert Settings().public_url("http://internal/ab.mp3") == "http://internal/ab.mp3"
