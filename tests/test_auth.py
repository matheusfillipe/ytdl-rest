from __future__ import annotations

from ytdl_rest.auth import generate_key
from ytdl_rest.auth import hash_key
from ytdl_rest.auth import verify


def test_generated_keys_are_unique() -> None:
    assert generate_key() != generate_key()


def test_verify_accepts_the_matching_key() -> None:
    key = generate_key()
    assert verify(key, hash_key(key))


def test_verify_rejects_a_wrong_or_absent_key() -> None:
    assert not verify("nonsense", hash_key(generate_key()))
    assert not verify(None, hash_key(generate_key()))


def test_no_configured_hash_leaves_the_service_open() -> None:
    assert verify(None, None)
