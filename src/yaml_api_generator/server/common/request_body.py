"""Deferred request bodies of file entities.

The body is read only when the pipeline reaches its file step, so nothing is
stored before the route's access rules have passed.
"""

from collections.abc import AsyncIterator
from dataclasses import dataclass

from fastapi import Request
from pydantic import BaseModel

from yaml_api_generator.runtime.file_requests import (
    Reader,
    read_record,
    read_upload,
    upload_parts,
)
from yaml_api_generator.runtime.files import Ingest, RecordFiles
from yaml_api_generator.runtime.multipart import UploadPart


@dataclass(frozen=True)
class RequestBody:
    """The multipart parts of a file endpoint."""

    request: Request

    def parts(self) -> AsyncIterator[UploadPart]:
        return upload_parts(self.request)


@dataclass(frozen=True)
class RecordBody(RequestBody):
    """A record write: record fields validated by `model`, plus its file parts."""

    model: type[BaseModel]
    partial: bool = False
    read: Reader = read_upload

    async def ingest(self, files: RecordFiles) -> Ingest:
        return await read_record(
            self.request, files, self.model, partial=self.partial, read=self.read
        )
