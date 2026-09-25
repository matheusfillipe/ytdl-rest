# ytdl-rest

Downloads anything [yt-dlp](https://github.com/yt-dlp/yt-dlp) supports, at the quality and format you
ask for, and republishes it to a [girafiles](https://github.com/matheusfillipe/girafiles) host so the
answer is a temporary link anyone can open. REST and MCP, one URL and one key for both.

## Run it

```bash
uv sync --extra dev
uv run python -m ytdl_rest              # API on :8000, docs at /docs, MCP at /mcp
uv run python -m ytdl_rest keygen       # an API key and the hash to deploy
```

```bash
curl -X POST localhost:8000/v1/download -H 'content-type: application/json' \
  -d '{"url":"https://youtu.be/...","mode":"audio","format":"mp3","quality":"192"}'
# {"url":"https://s.example.com/ab.mp3","title":"...","duration":213.0,"size_bytes":5111808,...}
```

To keep the file private, `POST /v1/file` takes the same body and answers with the file itself, with
`X-Media-Title` (URL-encoded) and `X-Media-Duration` headers.

Every setting is an environment variable prefixed `YTDL_`; see [`.env.example`](.env.example).
