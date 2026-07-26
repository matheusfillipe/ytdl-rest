"""Run the HTTP API, or the MCP server, from one entry point."""

from __future__ import annotations

import argparse

from ytdl_rest.config import get_settings


def main() -> None:
    parser = argparse.ArgumentParser(prog="ytdl-rest")
    parser.add_argument("surface", choices=("api", "mcp", "keygen"), nargs="?", default="api")
    args = parser.parse_args()

    if args.surface == "keygen":
        from ytdl_rest.auth import generate_key
        from ytdl_rest.auth import hash_key

        key = generate_key()
        print("Give this key to callers. It is not stored anywhere and cannot be recovered:")
        print(f"  {key}")
        print()
        print("Deploy this hash as YTDL_API_KEY_HASH. It cannot be used to call the service:")
        print(f"  {hash_key(key)}")
        return

    settings = get_settings()

    if args.surface == "mcp":
        from ytdl_rest.mcp import create_mcp

        create_mcp(settings).run()
        return

    import uvicorn

    uvicorn.run(
        "ytdl_rest.api:app",
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level,
    )


if __name__ == "__main__":
    main()
