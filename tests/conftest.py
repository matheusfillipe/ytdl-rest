from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from ytdl_rest.config import Settings

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        upload_url="http://filehost.test/api/",
        upload_public_base="https://s.test",
        work_dir=tmp_path,
        max_file_bytes=1_000_000,
    )
