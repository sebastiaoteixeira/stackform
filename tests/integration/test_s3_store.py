"""S3Store against a real MinIO."""

import hashlib
from uuid import uuid4

import pytest

from tests.integration.support.minio import CREDENTIALS, s3_client
from yaml_api_generator.runtime.files import (
    FileField,
    FileLimits,
    FileTooLargeError,
    RecordFiles,
    StoredFileNotFoundError,
)
from yaml_api_generator.runtime.multipart import UploadPart
from yaml_api_generator.runtime.s3_store import PART_SIZE, S3Store

pytestmark = pytest.mark.integration


class Interrupted(Exception):
    pass


@pytest.fixture
def bucket():
    return f"test-{uuid4().hex[:12]}"


@pytest.fixture
async def store(s3_endpoint, bucket):
    store = S3Store(bucket, endpoint=s3_endpoint, prefix="/uploads/", create_bucket=True, **CREDENTIALS)
    await store.open()
    yield store
    await store.close()


@pytest.fixture
async def bucket_contents(s3_endpoint, bucket):
    """Raw view of the bucket, independent of the store under test."""
    async with s3_client(s3_endpoint) as client:

        async def contents() -> tuple[list[str], list[str]]:
            listed = await client.list_objects_v2(Bucket=bucket)
            pending = await client.list_multipart_uploads(Bucket=bucket)
            return (
                [item["Key"] for item in listed.get("Contents", [])],
                [item["Key"] for item in pending.get("Uploads", [])],
            )

        yield contents


async def stream(payload: bytes, size: int = 1024**2, fail_after: int | None = None):
    for start in range(0, len(payload), size):
        if fail_after is not None and start >= fail_after:
            raise Interrupted
        yield payload[start : start + size]


async def read(store: S3Store, key: str) -> bytes:
    return b"".join([chunk async for chunk in store.get(key)])


@pytest.mark.parametrize("size", [0, 1, 70_000, PART_SIZE, 2 * PART_SIZE + 123])
async def test_round_trip(store, bucket_contents, size):
    payload = (hashlib.sha256(str(size).encode()).digest() * (size // 32 + 1))[:size]

    await store.put("posts/f1", stream(payload))

    assert await read(store, "posts/f1") == payload
    assert await bucket_contents() == (["uploads/posts/f1"], [])


async def test_failed_multipart_upload_is_aborted(store, bucket_contents):
    with pytest.raises(Interrupted):
        await store.put("posts/f1", stream(b"x" * (3 * PART_SIZE), fail_after=2 * PART_SIZE))

    assert await bucket_contents() == ([], [])


async def test_failed_small_upload_leaves_nothing(store, bucket_contents):
    with pytest.raises(Interrupted):
        await store.put("posts/f1", stream(b"x" * 4096, size=1024, fail_after=2048))

    assert await bucket_contents() == ([], [])


async def test_delete_is_idempotent_and_missing_files_are_not_found(store):
    await store.put("posts/f1", stream(b"data"))

    await store.delete("posts/f1")
    await store.delete("posts/f1")

    with pytest.raises(StoredFileNotFoundError):
        await read(store, "posts/f1")


async def test_reopening_an_existing_bucket_without_prefix(s3_endpoint, bucket, store, bucket_contents):
    again = S3Store(bucket, endpoint=s3_endpoint, create_bucket=True, **CREDENTIALS)
    await again.open()
    try:
        await again.put("k", stream(b"v"))
        assert await read(again, "k") == b"v"
    finally:
        await again.close()

    assert await bucket_contents() == (["k"], [])


async def test_record_files_on_s3(store, bucket_contents):
    field = FileField("cover", "media", FileLimits(max_size=1024, types=("application/pdf",)))
    files = RecordFiles("posts", {"cover": field}, {"media": store})
    pdf = b"%PDF-1.4\n" + b"0" * 500

    async def parts(*items):
        for item in items:
            yield item

    ingest = await files.ingest_multipart(
        parts(UploadPart("cover", "a.pdf", "application/pdf", stream(pdf, size=100))), partial=False
    )
    download = files.download(ingest.files, "cover")

    assert b"".join([chunk async for chunk in download.chunks]) == pdf
    assert await bucket_contents() == ([f"uploads/posts/{ingest.files['cover']['id']}"], [])
    with pytest.raises(FileTooLargeError):
        await files.ingest_multipart(
            parts(UploadPart("cover", "b.pdf", None, stream(pdf * 3, size=100))), partial=False
        )
    await files.discard(files.attached(ingest.files))
    assert await bucket_contents() == ([], [])
