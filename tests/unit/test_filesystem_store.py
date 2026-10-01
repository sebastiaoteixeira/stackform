import hashlib

import pytest

from yaml_api_generator.runtime.files import StoredFileNotFoundError
from yaml_api_generator.runtime.filesystem_store import FilesystemStore


class Interrupted(Exception):
    pass


async def stream(*chunks: bytes, fail: bool = False):
    for chunk in chunks:
        yield chunk
    if fail:
        raise Interrupted


async def read(store: FilesystemStore, key: str) -> bytes:
    return b"".join([chunk async for chunk in store.get(key)])


def stored_files(root) -> list[str]:
    return sorted(str(path.relative_to(root)) for path in root.rglob("*") if path.is_file())


@pytest.fixture
async def store(tmp_path):
    store = FilesystemStore(tmp_path / "files")
    await store.open()
    yield store
    await store.close()


async def test_round_trip_streams_large_files_in_bounded_chunks(store, tmp_path):
    payload = hashlib.sha256(b"seed").digest() * 20_000

    await store.put("posts/abc", stream(payload[:100_000], payload[100_000:]))
    chunks = [chunk async for chunk in store.get("posts/abc")]

    assert b"".join(chunks) == payload
    assert max(map(len, chunks)) <= 64 * 1024
    assert stored_files(tmp_path / "files") == ["posts/abc"]


async def test_put_replaces_existing_bytes(store):
    await store.put("posts/abc", stream(b"old"))
    await store.put("posts/abc", stream(b"new"))

    assert await read(store, "posts/abc") == b"new"


async def test_failed_put_leaves_nothing_behind(store, tmp_path):
    with pytest.raises(Interrupted):
        await store.put("posts/abc", stream(b"partial", b"bytes", fail=True))

    assert stored_files(tmp_path / "files") == []
    with pytest.raises(StoredFileNotFoundError):
        store.get("posts/abc")


async def test_delete_is_idempotent(store):
    await store.put("posts/abc", stream(b"data"))

    await store.delete("posts/abc")
    await store.delete("posts/abc")

    with pytest.raises(StoredFileNotFoundError):
        store.get("posts/abc")


async def test_open_creates_the_root(tmp_path):
    store = FilesystemStore(str(tmp_path / "nested" / "root"))
    await store.open()

    await store.put("a/b", stream(b"x"))

    assert (tmp_path / "nested" / "root" / "a" / "b").read_bytes() == b"x"


@pytest.mark.parametrize(
    "key",
    ["../escape", "posts/../../escape", "/etc/passwd", "posts\\abc", ".tmp/abc", "", "posts/./abc"],
)
async def test_unsafe_keys_are_rejected(store, key):
    with pytest.raises(ValueError):
        await store.put(key, stream(b"x"))
    with pytest.raises(ValueError):
        store.get(key)
    with pytest.raises(ValueError):
        await store.delete(key)
