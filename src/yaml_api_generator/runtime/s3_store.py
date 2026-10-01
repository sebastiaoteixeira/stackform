"""FileStore keeping file bytes in an S3-compatible bucket."""

from collections.abc import AsyncIterable, AsyncIterator
from contextlib import AsyncExitStack, suppress
from typing import Any

import anyio
from aiobotocore.session import get_session

from .files import StoredFileNotFoundError

PART_SIZE = 8 * 1024**2
CHUNK_SIZE = 64 * 1024
DEFAULT_REGION = "us-east-1"


async def _parts(chunks: AsyncIterable[bytes], size: int) -> AsyncIterator[bytes]:
    buffer = bytearray()
    async for chunk in chunks:
        buffer += chunk
        while len(buffer) >= size:
            yield bytes(buffer[:size])
            del buffer[:size]
    if buffer:
        yield bytes(buffer)


class S3Store:
    def __init__(
        self,
        bucket: str,
        *,
        endpoint: str | None = None,
        region: str | None = None,
        access_key: str | None = None,
        secret_key: str | None = None,
        prefix: str = "",
        create_bucket: bool = False,
    ) -> None:
        self._bucket = bucket
        self._region = region
        self._prefix = f"{prefix.strip('/')}/" if prefix.strip("/") else ""
        self._create_bucket = create_bucket
        self._options = {
            name: value
            for name, value in {
                "endpoint_url": endpoint,
                "region_name": region,
                "aws_access_key_id": access_key,
                "aws_secret_access_key": secret_key,
            }.items()
            if value
        }
        self._stack = AsyncExitStack()
        self._client: Any = None

    async def open(self) -> None:
        self._client = await self._stack.enter_async_context(
            get_session().create_client("s3", **self._options)
        )
        if self._create_bucket:
            await self._ensure_bucket()

    async def close(self) -> None:
        await self._stack.aclose()

    async def put(self, key: str, chunks: AsyncIterable[bytes]) -> None:
        parts = _parts(chunks, PART_SIZE)
        first = await anext(parts, b"")
        if len(first) < PART_SIZE:
            await self._client.put_object(Bucket=self._bucket, Key=self._key(key), Body=first)
            return
        await self._put_multipart(self._key(key), first, parts)

    async def get(self, key: str) -> AsyncIterator[bytes]:
        try:
            response = await self._client.get_object(Bucket=self._bucket, Key=self._key(key))
        except self._client.exceptions.NoSuchKey as error:
            raise StoredFileNotFoundError(f"Stored file '{key}' not found") from error
        async with response["Body"] as body:
            async for chunk in body.iter_chunks(CHUNK_SIZE):
                yield chunk

    async def delete(self, key: str) -> None:
        await self._client.delete_object(Bucket=self._bucket, Key=self._key(key))

    def _key(self, key: str) -> str:
        return f"{self._prefix}{key}"

    async def _put_multipart(self, key: str, first: bytes, rest: AsyncIterator[bytes]) -> None:
        location = {"Bucket": self._bucket, "Key": key}
        upload = await self._client.create_multipart_upload(**location)
        location["UploadId"] = upload["UploadId"]
        completed: list[dict[str, Any]] = []
        try:
            body = first
            while body:
                number = len(completed) + 1
                response = await self._client.upload_part(**location, PartNumber=number, Body=body)
                completed.append({"PartNumber": number, "ETag": response["ETag"]})
                body = await anext(rest, b"")
            await self._client.complete_multipart_upload(
                **location, MultipartUpload={"Parts": completed}
            )
        except BaseException:
            with anyio.CancelScope(shield=True):
                await self._client.abort_multipart_upload(**location)
            raise

    async def _ensure_bucket(self) -> None:
        location = (
            {"CreateBucketConfiguration": {"LocationConstraint": self._region}}
            if self._region and self._region != DEFAULT_REGION
            else {}
        )
        with suppress(
            self._client.exceptions.BucketAlreadyOwnedByYou,
            self._client.exceptions.BucketAlreadyExists,
        ):
            await self._client.create_bucket(Bucket=self._bucket, **location)
