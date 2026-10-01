"""File pipeline steps.

A write step stores the new bytes, runs the record write, then drops the files
the write orphaned; when the write fails, it drops the files it stored instead.
"""

from collections.abc import Awaitable, Callable, Mapping
from typing import Any, TypeVar

from yaml_api_generator.runtime.files import (
    FileMetadata,
    InvalidMultipartError,
    RecordFiles,
)

from ..request_body import RecordBody, RequestBody
from ..request_context import RequestContext
from . import Step

FILE_ID = "fileId"

Body = TypeVar("Body", bound=RequestBody)

AsyncStep = Callable[[RequestContext], Awaitable[RequestContext]]
FileChange = Callable[
    [RecordFiles, RequestContext, Mapping[str, Any]],
    Awaitable[tuple[dict[str, Any], tuple[FileMetadata, ...]]],
]


def _upload(ctx: RequestContext, kind: type[Body]) -> Body:
    if not isinstance(ctx.upload, kind):
        raise InvalidMultipartError("Request body is missing")
    return ctx.upload


async def ingest_upload(
    files: RecordFiles, ctx: RequestContext, record: Mapping[str, Any]
) -> tuple[dict[str, Any], tuple[FileMetadata, ...]]:
    ingest = await _upload(ctx, RecordBody).ingest(files)
    kept = {name: record[name] for name in files.fields if name in record}
    return {**kept, **ingest.data, **ingest.files}, ingest.stored


def replace_file(field: str) -> FileChange:
    async def change(
        files: RecordFiles, ctx: RequestContext, record: Mapping[str, Any]
    ) -> tuple[dict[str, Any], tuple[FileMetadata, ...]]:
        value, stored = await files.replace(
            record, field, _upload(ctx, RequestBody).parts(), ctx.url_params.get(FILE_ID)
        )
        return {field: value}, stored

    return change


def remove_file(field: str) -> FileChange:
    async def change(
        files: RecordFiles, ctx: RequestContext, record: Mapping[str, Any]
    ) -> tuple[dict[str, Any], tuple[FileMetadata, ...]]:
        return {field: files.remove(record, field, ctx.url_params.get(FILE_ID))}, ()

    return change


def FileWriteStep(files: RecordFiles, change: FileChange, write: AsyncStep) -> Step:
    async def step(ctx: RequestContext) -> RequestContext:
        before = ctx.response if isinstance(ctx.response, dict) else {}
        ctx.body, stored = await change(files, ctx, before)
        try:
            ctx = await write(ctx)
        except BaseException:
            await files.discard(stored)
            raise
        await files.discard(files.orphaned(before, ctx.response))
        return ctx

    return step


def DownloadFileStep(files: RecordFiles, field: str) -> Step:
    def step(ctx: RequestContext) -> RequestContext:
        ctx.response = files.download(ctx.response, field, ctx.url_params.get(FILE_ID))
        return ctx

    return step


def DiscardFilesStep(files: RecordFiles) -> Step:
    async def step(ctx: RequestContext) -> RequestContext:
        await files.discard(files.attached(ctx.response))
        return ctx

    return step
