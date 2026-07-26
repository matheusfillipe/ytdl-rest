from __future__ import annotations

from pathlib import Path
from typing import Any
from typing import ClassVar
from typing import Self

import pytest
import yt_dlp

from ytdl_rest import download
from ytdl_rest.config import Settings
from ytdl_rest.download import ExtractionError
from ytdl_rest.download import Request
from ytdl_rest.download import UnsupportedRequestError


class FakeYoutubeDL:
    """Stands in for yt-dlp: writes the file the real one would have produced."""

    written = b"x" * 32
    info: ClassVar[dict[str, Any]] = {"title": "A Song", "duration": 12.0, "extractor_key": "Fake", "webpage_url": "u"}
    extras: ClassVar[list[str]] = []

    def __init__(self, options: dict[str, Any]) -> None:
        self.options = options
        self.outdir = Path(options["outtmpl"]).parent

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def extract_info(self, url: str, download: bool = True) -> dict[str, Any] | None:
        if download:
            (self.outdir / "media.mp3").write_bytes(self.written)
            for name in self.extras:
                (self.outdir / name).write_bytes(b"y")
        return dict(self.info)


def test_resolve_fills_defaults_from_settings() -> None:
    settings = Settings(default_mode="audio", default_audio_format="opus", default_audio_quality="best")
    request = download.resolve(settings, "u", None, None, None)
    assert request == Request(url="u", mode="audio", quality="best", format="opus")


@pytest.mark.parametrize(
    ("mode", "quality", "fmt"),
    [
        ("sideways", None, None),
        ("video", "1080p", "mp4"),
        ("video", "best", "mp3"),
        ("audio", "best", "mkv"),
        ("audio", "lossless", "mp3"),
    ],
)
def test_resolve_rejects_what_cannot_be_served(mode: str, quality: str | None, fmt: str | None) -> None:
    with pytest.raises(UnsupportedRequestError):
        download.resolve(Settings(), "u", mode, quality, fmt)


def test_format_selector_caps_height_when_a_quality_is_given() -> None:
    assert "height<=720" in download.format_selector(Request("u", "video", "720", "mp4"))
    assert download.format_selector(Request("u", "video", "best", "mp4")) == "bv*+ba/b"
    assert download.format_selector(Request("u", "video", "worst", "mp4")) == "wv*+wa/w"
    assert download.format_selector(Request("u", "audio", "best", "mp3")) == "bestaudio/best"


def test_video_options_merge_into_the_requested_container(settings: Settings, tmp_path: Path) -> None:
    options = download.build_options(settings, Request("u", "video", "1080", "mkv"), tmp_path)
    assert options["merge_output_format"] == "mkv"
    assert options["max_filesize"] == settings.max_file_bytes
    assert "postprocessors" not in options


def test_audio_options_extract_the_requested_codec_and_bitrate(settings: Settings, tmp_path: Path) -> None:
    options = download.build_options(settings, Request("u", "audio", "192", "mp3"), tmp_path)
    postprocessor = options["postprocessors"][0]
    assert postprocessor["preferredcodec"] == "mp3"
    assert postprocessor["preferredquality"] == "192"


def test_best_audio_quality_asks_ffmpeg_for_the_codec_default(settings: Settings, tmp_path: Path) -> None:
    options = download.build_options(settings, Request("u", "audio", "best", "opus"), tmp_path)
    assert options["postprocessors"][0]["preferredquality"] == "0"


def test_extraction_settings_reach_yt_dlp(tmp_path: Path) -> None:
    cookies = tmp_path / "cookies.txt"
    cookies.write_text("# Netscape HTTP Cookie File\n")
    settings = Settings(
        cookies_file=cookies,
        pot_provider_url="http://pot:4416",
        proxy="socks5://proxy:1080",
        user_agent="agent/1",
        max_duration_seconds=60,
        extra_options={"retries": 9},
    )
    options = download.build_options(settings, Request("u", "video", "best", "mp4"), tmp_path)
    assert Path(options["cookiefile"]).read_text() == cookies.read_text()
    assert options["extractor_args"]["youtubepot-bgutilhttp"]["base_url"] == ["http://pot:4416"]
    assert options["proxy"] == "socks5://proxy:1080"
    assert options["http_headers"]["User-Agent"] == "agent/1"
    assert options["match_filter"] is not None
    assert options["retries"] == 9


def test_run_returns_the_downloaded_file(settings: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(yt_dlp, "YoutubeDL", FakeYoutubeDL)
    media = download.run(settings, Request("u", "audio", "best", "mp3"), tmp_path)
    assert media.path.name == "media.mp3"
    assert media.title == "A Song"
    assert media.size_bytes == len(FakeYoutubeDL.written)


def test_run_ignores_sidecars_and_keeps_the_media(
    settings: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(yt_dlp, "YoutubeDL", FakeYoutubeDL)
    monkeypatch.setattr(FakeYoutubeDL, "extras", ["media.jpg", "media.en.vtt", "media.mp3.part"])
    media = download.run(settings, Request("u", "audio", "best", "mp3"), tmp_path)
    assert media.path.name == "media.mp3"


def test_run_refuses_a_result_over_the_size_cap(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(yt_dlp, "YoutubeDL", FakeYoutubeDL)
    settings = Settings(max_file_bytes=4)
    with pytest.raises(ExtractionError, match="exceeds"):
        download.run(settings, Request("u", "audio", "best", "mp3"), tmp_path)


def test_run_reports_when_nothing_matched(settings: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    class Empty(FakeYoutubeDL):
        def extract_info(self, url: str, download: bool = True) -> dict[str, Any] | None:
            return None

    monkeypatch.setattr(yt_dlp, "YoutubeDL", Empty)
    with pytest.raises(ExtractionError):
        download.run(settings, Request("u", "audio", "best", "mp3"), tmp_path)


def test_run_takes_the_first_entry_of_a_playlist(
    settings: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Playlist(FakeYoutubeDL):
        def extract_info(self, url: str, download: bool = True) -> dict[str, Any] | None:
            super().extract_info(url, download)
            return {"entries": [None, {"title": "Second", "webpage_url": "u2"}]}

    monkeypatch.setattr(yt_dlp, "YoutubeDL", Playlist)
    assert download.run(settings, Request("u", "audio", "best", "mp3"), tmp_path).title == "Second"


def test_probe_returns_metadata_without_downloading(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    class Prober(FakeYoutubeDL):
        def __init__(self, options: dict[str, Any]) -> None:
            self.options = options

        def extract_info(self, url: str, download: bool = True) -> dict[str, Any] | None:
            assert download is False
            return {"title": "T", "duration": 3.0, "formats": [{"format_id": "18", "ext": "mp4", "height": 360}]}

    monkeypatch.setattr(yt_dlp, "YoutubeDL", Prober)
    info = download.probe(settings, "u")
    assert info["title"] == "T"
    assert info["formats"][0]["height"] == 360


def test_cookies_are_copied_somewhere_writable(tmp_path: Path) -> None:
    source = tmp_path / "mounted" / "cookies.txt"
    source.parent.mkdir()
    source.write_text("# Netscape HTTP Cookie File\n")
    source.chmod(0o444)
    outdir = tmp_path / "work"
    outdir.mkdir()

    settings = Settings(cookies_file=source)
    options = download.build_options(settings, Request("u", "audio", "best", "mp3"), outdir)

    copy = Path(options["cookiefile"])
    assert copy != source
    assert copy.read_text() == source.read_text()
    # yt-dlp saves the jar back on close, so the copy has to be writable.
    copy.write_text("changed")
    # And it must not be mistaken for the downloaded media.
    assert copy.parent != outdir


def test_missing_cookie_file_is_simply_skipped(tmp_path: Path) -> None:
    settings = Settings(cookies_file=tmp_path / "absent.txt")
    options = download.build_options(settings, Request("u", "audio", "best", "mp3"), tmp_path)
    assert "cookiefile" not in options
