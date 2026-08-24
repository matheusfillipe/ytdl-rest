FROM python:3.12-slim

# ffmpeg does the muxing and the audio extraction; without it only pre-muxed formats work.
RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg curl && \
    rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# yt-dlp solves YouTube's nsig challenges in JavaScript, and deno is the runtime it picks by default.
COPY --from=denoland/deno:bin-2.9.5 /deno /usr/local/bin/deno

WORKDIR /app

# Lockfile first, so dependency layers survive a source change.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY . .
RUN uv sync --frozen --no-dev

# An extractor a release behind answers 403, so the image carries the newest yt-dlp at build time.
RUN uv pip install --python .venv --upgrade yt-dlp yt-dlp-ejs

# The home directory has to be writable: yt-dlp caches the solved signature functions under it,
# and without the cache every request re-fetches the player JS and re-runs the solver.
RUN adduser --system --home /app app && chown -R app /app
USER app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/v1/health || exit 1

CMD [".venv/bin/python", "-m", "ytdl_rest", "api"]
