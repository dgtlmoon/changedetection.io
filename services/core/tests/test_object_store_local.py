"""LocalObjectStore — filesystem backend, no DB."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.object_store import InvalidObjectKey, LocalObjectStore, ObjectNotFound


@pytest.fixture
def store(tmp_path: Path) -> LocalObjectStore:
    return LocalObjectStore(tmp_path / "blobs")


@pytest.mark.asyncio
async def test_put_then_get_roundtrip(store: LocalObjectStore) -> None:
    await store.put("org-a/watches/w1/snap.brotli", b"hello", content_type="text/plain")
    got = await store.get("org-a/watches/w1/snap.brotli")
    assert got == b"hello"


@pytest.mark.asyncio
async def test_put_overwrite(store: LocalObjectStore) -> None:
    await store.put("k", b"v1", content_type="text/plain")
    await store.put("k", b"v2", content_type="text/plain")
    assert (await store.get("k")) == b"v2"


@pytest.mark.asyncio
async def test_get_missing_raises(store: LocalObjectStore) -> None:
    with pytest.raises(ObjectNotFound):
        await store.get("nope/x")


@pytest.mark.asyncio
async def test_delete_removes_and_then_raises(store: LocalObjectStore) -> None:
    await store.put("k", b"x", content_type="text/plain")
    await store.delete("k")
    assert (await store.exists("k")) is False
    with pytest.raises(ObjectNotFound):
        await store.delete("k")


@pytest.mark.asyncio
async def test_exists(store: LocalObjectStore) -> None:
    assert (await store.exists("nope")) is False
    await store.put("yes", b"", content_type="text/plain")
    assert (await store.exists("yes")) is True


@pytest.mark.asyncio
async def test_presigned_url_is_file_uri(store: LocalObjectStore) -> None:
    await store.put("a/b/c.txt", b"", content_type="text/plain")
    url = await store.presigned_url("a/b/c.txt")
    assert url.startswith("file://")


# ---------------------------------------------------------------------------
# Key validation — path traversal + friends
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad_key",
    [
        "../etc/passwd",
        "/etc/passwd",
        "org/../other/snap",
        "org/..",
        "back\\slash",
        "",
        "has null\x00",
        "x" * 1200,
    ],
)
@pytest.mark.asyncio
async def test_path_traversal_keys_rejected(
    store: LocalObjectStore, bad_key: str
) -> None:
    with pytest.raises(InvalidObjectKey):
        await store.put(bad_key, b"x", content_type="text/plain")


@pytest.mark.asyncio
async def test_valid_nested_key_works(store: LocalObjectStore) -> None:
    """Keys with many slashes are fine; we just reject ``..`` and leading ``/``."""
    key = "org-123/watches/abcd/snapshots/2026-04-13T12-34-56.brotli"
    await store.put(key, b"nested", content_type="text/plain")
    assert (await store.get(key)) == b"nested"
