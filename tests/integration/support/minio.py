"""A real MinIO: YAML_API_TEST_S3_ENDPOINT when set, otherwise a throwaway container."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from aiobotocore.session import get_session

from .docker import Service

ROOT_USER = ROOT_PASSWORD = "minioadmin"
CREDENTIALS = {"access_key": ROOT_USER, "secret_key": ROOT_PASSWORD}


def _live(endpoint: str) -> bool:
    try:
        return httpx.get(f"{endpoint}/minio/health/live", timeout=1).is_success
    except httpx.HTTPError:
        return False


MINIO = Service(
    name="minio",
    image="minio/minio",
    port=9000,
    scheme="http",
    override="YAML_API_TEST_S3_ENDPOINT",
    ready=_live,
    env={"MINIO_ROOT_USER": ROOT_USER, "MINIO_ROOT_PASSWORD": ROOT_PASSWORD},
    command=("server", "/data"),
)


@asynccontextmanager
async def s3_client(endpoint: str) -> AsyncIterator:
    """A raw S3 client, independent of the store under test."""
    async with get_session().create_client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=ROOT_USER,
        aws_secret_access_key=ROOT_PASSWORD,
        region_name="us-east-1",
    ) as client:
        yield client


async def object_keys(endpoint: str, bucket: str) -> list[str]:
    async with s3_client(endpoint) as client:
        listed = await client.list_objects_v2(Bucket=bucket)
    return sorted(item["Key"] for item in listed.get("Contents", []))
