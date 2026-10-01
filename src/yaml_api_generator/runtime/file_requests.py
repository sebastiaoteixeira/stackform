"""FastAPI request bodies of records with file fields: negotiation, validation and cleanup on failure."""

from collections.abc import AsyncIterator, Awaitable, Callable, Iterable, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass, replace
from typing import Any

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, ValidationError

from .files import FileMetadata, Ingest, RecordFiles
from .multipart import UploadPart, is_multipart, multipart_request_body, read_multipart

Reader = Callable[..., Awaitable[Ingest]]


def upload_parts(request: Request) -> AsyncIterator[UploadPart]:
    return read_multipart(request.headers.get("content-type", ""), request.stream())


async def json_body(request: Request) -> dict[str, Any]:
    try:
        body = await request.json()
    except ValueError as error:
        raise RequestValidationError(
            [{"type": "json_invalid", "loc": ("body",), "msg": "Invalid JSON body", "input": None}]
        ) from error
    if not isinstance(body, dict):
        raise RequestValidationError(
            [{"type": "dict_type", "loc": ("body",), "msg": "Input should be a JSON object", "input": body}]
        )
    return body


async def read_upload(request: Request, files: RecordFiles, *, partial: bool) -> Ingest:
    """Multipart with a `_data` part and file parts, or plain JSON without file keys."""
    if is_multipart(request.headers.get("content-type")):
        return await files.ingest_multipart(upload_parts(request), partial=partial)
    return files.ingest_json(await json_body(request), partial=partial)


async def read_json(request: Request, files: RecordFiles, *, partial: bool) -> Ingest:
    """JSON without file keys; the route carries the stored file values over."""
    return files.ingest_json(await json_body(request), partial=True)


def validated(model: type[BaseModel], data: Mapping[str, Any], *, partial: bool) -> dict[str, Any]:
    try:
        return model.model_validate(data).model_dump(mode="json", exclude_unset=partial)
    except ValidationError as error:
        raise RequestValidationError(
            [{**issue, "loc": ("body", *issue["loc"])} for issue in error.errors(include_url=False)],
            body=data,
        ) from error


@asynccontextmanager
async def discard_on_error(files: RecordFiles, stored: Iterable[FileMetadata]) -> AsyncIterator[None]:
    try:
        yield
    except Exception:
        await files.discard(stored)
        raise


async def read_record(
    request: Request,
    files: RecordFiles,
    model: type[BaseModel],
    *,
    partial: bool,
    read: Reader = read_upload,
) -> Ingest:
    """The stored upload with `data` validated by `model`; nothing stays stored when validation fails."""
    ingest = await read(request, files, partial=partial)
    async with discard_on_error(files, ingest.stored):
        return replace(ingest, data=validated(model, ingest.data, partial=partial))


@dataclass(frozen=True)
class RecordUpload:
    payload: dict[str, Any]
    files: dict[str, Any]

    @property
    def record(self) -> dict[str, Any]:
        return {**self.payload, **self.files}


def record_upload(
    files: RecordFiles, model: type[BaseModel], *, partial: bool, read: Reader = read_upload
) -> Callable[[Request], AsyncIterator[RecordUpload]]:
    """Dependency yielding the validated upload; its stored files are discarded if the request fails."""

    async def dependency(request: Request) -> AsyncIterator[RecordUpload]:
        ingest = await read_record(request, files, model, partial=partial, read=read)
        async with discard_on_error(files, ingest.stored):
            yield RecordUpload(ingest.data, ingest.files)

    return dependency


def carried_files(files: RecordFiles, record: Mapping[str, Any]) -> dict[str, Any]:
    return {name: record.get(name) for name in files.fields}


def upload_request_body(files: RecordFiles, model: type[BaseModel], *, partial: bool) -> dict[str, Any]:
    return multipart_request_body(model.model_json_schema(), files.fields.values(), partial=partial)


def json_request_body(_: RecordFiles, model: type[BaseModel], *, partial: bool) -> dict[str, Any]:
    return {"required": True, "content": {"application/json": {"schema": model.model_json_schema()}}}
