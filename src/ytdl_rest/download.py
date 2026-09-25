"""The yt-dlp side: turn a request into one file on local disk."""

from __future__ import annotations

import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yt_dlp
from yt_dlp.utils import DownloadError
from yt_dlp.utils import match_filter_func

from ytdl_rest.config import AUDIO_FORMATS
from ytdl_rest.config import VIDEO_FORMATS
from ytdl_rest.config import Mode
from ytdl_rest.config import Settings

OUTPUT_TEMPLATE = "%(title).150B [%(id)s].%(ext)s"
FFPROBE_TIMEOUT_SECONDS = 30


class UnsupportedRequestError(ValueError):
    """The mode, container or quality asked for is not one this service offers."""


class ExtractionError(RuntimeError):
    """yt-dlp could not produce a file. Its own message is the useful part."""


@dataclass(frozen=True)
class Request:
    url: str
    mode: Mode
    quality: str
    format: str


@dataclass(frozen=True)
class Media:
    path: Path
    title: str
    duration: float | None
    extractor: str
    webpage_url: str

    @property
    def size_bytes(self) -> int:
        return self.path.stat().st_size


def resolve(settings: Settings, url: str, mode: str | None, quality: str | None, format: str | None) -> Request:
    """Fill a request from its defaults and reject what cannot be served."""
    resolved_mode: Mode
    match mode or settings.default_mode:
        case "video":
            resolved_mode = "video"
        case "audio":
            resolved_mode = "audio"
        case other:
            raise UnsupportedRequestError(f"mode must be 'video' or 'audio', not {other!r}")

    if resolved_mode == "video":
        container = (format or settings.default_video_format).lower()
        if container not in VIDEO_FORMATS:
            raise UnsupportedRequestError(f"format must be one of {list(VIDEO_FORMATS)} for video")
        wanted = (quality or settings.default_video_quality).lower()
        if wanted not in ("best", "worst") and not wanted.isdigit():
            raise UnsupportedRequestError("quality must be 'best', 'worst' or a height in pixels, such as '1080'")
    else:
        container = (format or settings.default_audio_format).lower()
        if container not in AUDIO_FORMATS:
            raise UnsupportedRequestError(f"format must be one of {list(AUDIO_FORMATS)} for audio")
        wanted = (quality or settings.default_audio_quality).lower()
        if wanted != "best" and not wanted.isdigit():
            raise UnsupportedRequestError("quality must be 'best' or a bitrate in kbps, such as '192'")

    return Request(url=url, mode=resolved_mode, quality=wanted, format=container)


def format_selector(request: Request) -> str:
    if request.mode == "audio":
        return "bestaudio/best"
    if request.quality == "best":
        return "bv*+ba/b"
    if request.quality == "worst":
        return "wv*+wa/w"
    height = request.quality
    return f"bv*[height<={height}]+ba/b[height<={height}]/bv*+ba/b"


def writable_cookies(settings: Settings, outdir: Path) -> Path | None:
    """A throwaway copy of the cookie jar, because yt-dlp saves it back on close.

    The configured file is usually mounted read-only and refreshed underneath us, so it
    is copied per call rather than once: every request reads whatever is current, and
    yt-dlp's write lands somewhere that is discarded afterwards.
    """
    if not settings.cookies_file or not settings.cookies_file.exists():
        return None
    # A subdirectory, so the copy is never mistaken for the downloaded media.
    state = outdir / ".state"
    state.mkdir(exist_ok=True)
    copy = state / "cookies.txt"
    copy.write_bytes(settings.cookies_file.read_bytes())
    return copy


def build_options(settings: Settings, request: Request, outdir: Path) -> dict[str, Any]:
    """Every yt-dlp option this service sets, so it can be asserted on without downloading."""
    options: dict[str, Any] = {
        "outtmpl": str(outdir / OUTPUT_TEMPLATE),
        "format": format_selector(request),
        "noplaylist": not settings.allow_playlist,
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "restrictfilenames": True,
        # Refused while downloading rather than after uploading something the file host
        # would reject anyway.
        "max_filesize": settings.max_file_bytes,
        "retries": 3,
        "socket_timeout": 30,
    }

    if request.mode == "video":
        options["merge_output_format"] = request.format
    else:
        options["postprocessors"] = [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": request.format,
                # yt-dlp reads "0" as best available for the codec.
                "preferredquality": "0" if request.quality == "best" else request.quality,
            }
        ]

    if settings.max_duration_seconds > 0:
        options["match_filter"] = match_filter_func(f"duration < {settings.max_duration_seconds}")
    cookies = writable_cookies(settings, outdir)
    if cookies:
        options["cookiefile"] = str(cookies)
    if settings.proxy:
        options["proxy"] = settings.proxy
    if settings.user_agent:
        options["http_headers"] = {"User-Agent": settings.user_agent}
    if settings.pot_provider_url:
        options["extractor_args"] = {"youtubepot-bgutilhttp": {"base_url": [settings.pot_provider_url]}}

    options.update(settings.extra_options)
    return options


def _only_file(outdir: Path) -> Path:
    files = [path for path in outdir.iterdir() if path.is_file() and not path.name.endswith(".part")]
    if not files:
        raise ExtractionError("yt-dlp produced no file")
    # Largest wins: thumbnails and subtitle sidecars can appear alongside the media when
    # an extractor writes them regardless of what was asked for.
    return max(files, key=lambda path: path.stat().st_size)


def run(settings: Settings, request: Request, outdir: Path) -> Media:
    """Download one item. Blocking: yt-dlp is synchronous throughout."""
    options = build_options(settings, request, outdir)
    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(request.url, download=True)
    except DownloadError as error:
        raise ExtractionError(str(error)) from error

    if info is None:
        raise ExtractionError("nothing matched the requested filters")
    if "entries" in info:
        entries = [entry for entry in info["entries"] if entry]
        if not entries:
            raise ExtractionError("playlist contained nothing downloadable")
        info = entries[0]

    path = _only_file(outdir)
    if path.stat().st_size > settings.max_file_bytes:
        raise ExtractionError(f"result exceeds {settings.max_file_bytes} bytes")

    return Media(
        path=path,
        title=str(info.get("title") or path.stem),
        duration=info.get("duration"),
        extractor=str(info.get("extractor_key") or info.get("extractor") or "unknown"),
        webpage_url=str(info.get("webpage_url") or request.url),
    )


def file_duration(media_url: str | None) -> float | None:
    """Seconds of media behind a direct file link, which yt-dlp's generic extractor leaves unset.

    ffprobe reads only the headers it needs, and the protocol whitelist stops a crafted URL
    from reading local files through it.
    """
    if not media_url or not media_url.startswith(("http://", "https://")):
        return None
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-protocol_whitelist",
                "http,https,tcp,tls",
                "-show_entries",
                "format=duration",
                "-of",
                "csv=p=0",
                "-i",
                media_url,
            ],
            capture_output=True,
            text=True,
            timeout=FFPROBE_TIMEOUT_SECONDS,
            check=True,
        )
        return float(result.stdout.strip())
    except (subprocess.SubprocessError, ValueError, OSError):
        return None


def probe(settings: Settings, url: str) -> dict[str, Any]:
    """Metadata only, so a caller can choose a quality that exists."""
    options: dict[str, Any] = {"quiet": True, "no_warnings": True, "noplaylist": not settings.allow_playlist}
    if settings.proxy:
        options["proxy"] = settings.proxy
    if settings.pot_provider_url:
        options["extractor_args"] = {"youtubepot-bgutilhttp": {"base_url": [settings.pot_provider_url]}}
    options.update(settings.extra_options)

    try:
        with tempfile.TemporaryDirectory(dir=settings.work_dir) as scratch:
            cookies = writable_cookies(settings, Path(scratch))
            if cookies:
                options["cookiefile"] = str(cookies)
            with yt_dlp.YoutubeDL(options) as ydl:
                info = ydl.extract_info(url, download=False)
    except DownloadError as error:
        raise ExtractionError(str(error)) from error
    if info is None:
        raise ExtractionError("no metadata")

    formats = [
        {
            "format_id": item.get("format_id"),
            "ext": item.get("ext"),
            "height": item.get("height"),
            "abr": item.get("abr"),
            "filesize": item.get("filesize") or item.get("filesize_approx"),
        }
        for item in info.get("formats") or []
    ]
    return {
        "title": info.get("title"),
        "duration": info.get("duration") or file_duration(info.get("url")),
        "uploader": info.get("uploader"),
        "extractor": info.get("extractor_key") or info.get("extractor"),
        "webpage_url": info.get("webpage_url") or url,
        "thumbnail": info.get("thumbnail"),
        "formats": formats,
    }
