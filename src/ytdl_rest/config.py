"""Runtime configuration, entirely from the environment."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any
from typing import Literal

from pydantic import Field
from pydantic import field_validator
from pydantic_settings import BaseSettings
from pydantic_settings import SettingsConfigDict

Mode = Literal["video", "audio"]

VIDEO_FORMATS = ("mp4", "mkv", "webm")
AUDIO_FORMATS = ("mp3", "m4a", "opus", "flac", "wav", "vorbis", "aac")


class Settings(BaseSettings):
    """Every knob the service has. Prefix each with `YTDL_`."""

    model_config = SettingsConfigDict(env_prefix="YTDL_", env_file=".env", extra="ignore")

    # --- service ---
    host: str = "0.0.0.0"
    port: int = 8000
    log_level: str = "info"
    # The hash of the key, never the key itself, so the deployed secret cannot be used to
    # call the service. Generate both with `python -m ytdl_rest keygen`.
    api_key_hash: str | None = Field(
        default=None,
        description="SHA-256 of the API key. When set, callers must present the key itself.",
    )

    # --- file host ---
    # Any host speaking the girafiles API: multipart POST of a `file` field, answering
    # {"status": "success", "url": ...}. Point it at a cluster-internal address and let
    # public_base carry the name callers should see.
    upload_url: str = "http://localhost:8000/api/"
    upload_field: str = "file"
    # The name callers can reach. The host builds its link from whatever address this
    # service uploaded to, which is the wrong one when that address is cluster-internal.
    upload_public_base: str | None = None
    upload_basic_auth: str | None = Field(default=None, description="user:password, when the host requires it.")
    upload_timeout_seconds: float = 300.0

    # --- limits ---
    # Anything larger is refused mid-download rather than uploaded and rejected. Keep it
    # at or below whatever the file host accepts.
    max_file_bytes: int = 500 * 1024 * 1024
    max_duration_seconds: float = 0.0
    # Downloads are IO bound but each spends real CPU in ffmpeg when remuxing or
    # extracting audio, so the count is bounded rather than unbounded.
    max_concurrent_downloads: int = 2
    download_timeout_seconds: float = 1800.0
    allow_playlist: bool = False

    # --- extraction ---
    cookies_file: Path | None = None
    # A proof-of-origin token provider (bgutil), which YouTube increasingly requires.
    pot_provider_url: str | None = None
    proxy: str | None = None
    work_dir: Path | None = None
    user_agent: str | None = None
    # Escape hatch for anything yt-dlp accepts that has no setting of its own, as JSON.
    # Server-side only: callers cannot reach it, since yt-dlp options can write files.
    extra_options: dict[str, Any] = Field(default_factory=dict)

    # --- defaults for unspecified request fields ---
    default_mode: Mode = "video"
    default_video_quality: str = "best"
    default_video_format: str = "mp4"
    default_audio_quality: str = "best"
    default_audio_format: str = "mp3"

    @field_validator("extra_options", mode="before")
    @classmethod
    def _parse_extra_options(cls, value: object) -> object:
        if isinstance(value, str):
            return json.loads(value) if value.strip() else {}
        return value

    def public_url(self, url: str) -> str:
        """The link as callers should see it, when the file host reported another."""
        if not self.upload_public_base:
            return url
        return f"{self.upload_public_base.rstrip('/')}/{url.rsplit('/', 1)[-1]}"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Settings are read once; tests override by clearing this cache."""
    return Settings()
