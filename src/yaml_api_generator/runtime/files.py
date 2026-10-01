"""File fields: limits, upload guarding and record-level orchestration over a FileStore."""

import codecs
import hashlib
import json
import logging
import re
import unicodedata
from collections import defaultdict
from collections.abc import AsyncIterable, AsyncIterator, Iterable, Mapping
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from datetime import UTC, datetime
from itertools import chain
from typing import TYPE_CHECKING, Any, ClassVar, Protocol, Self
from urllib.parse import quote

import puremagic
from uuid_utils import uuid7

if TYPE_CHECKING:
    from .multipart import UploadPart


DEFAULT_MAX_SIZE = 10 * 1024**2
DEFAULT_MAX_FILES = 10
SNIFF_BYTES = 8192
DATA_PART_LIMIT = 1024**2
DATA_PART = "_data"
MAX_NAME_LENGTH = 255

_TEXTUAL_TYPES = ("application/json", "application/xml")
_TEXTUAL_SUFFIXES = ("+json", "+xml")
_INLINE_TYPES = ("image/*", "application/pdf", "audio/*", "video/*", "text/plain")
_INLINE_EXCLUDED = ("image/svg+xml",)
_PATH_SEPARATORS = re.compile(r"[/\\]")

logger = logging.getLogger(__name__)


class FileError(Exception):
    status_code: ClassVar[int]


class InvalidMultipartError(FileError):
    status_code = 400


class InvalidUploadError(FileError):
    status_code = 422


class MissingFileError(InvalidUploadError):
    pass


class FileTooLargeError(FileError):
    status_code = 413


class UnsupportedFileTypeError(FileError):
    status_code = 415


class StoredFileNotFoundError(FileError):
    status_code = 404


def media_type(value: str | None) -> str:
    return (value or "").split(";", 1)[0].strip().lower()


def matches(content_type: str, patterns: Iterable[str]) -> bool:
    return any(
        pattern == content_type
        or (pattern.endswith("/*") and content_type.startswith(pattern[:-1]))
        for pattern in patterns
    )


@dataclass(frozen=True)
class FileLimits:
    max_size: int = DEFAULT_MAX_SIZE
    types: tuple[str, ...] = ()

    def accepts(self, content_type: str) -> bool:
        return not self.types or matches(media_type(content_type), self.types)


@dataclass(frozen=True)
class FileField:
    name: str
    store: str
    limits: FileLimits = dataclass_field(default_factory=FileLimits)
    required: bool = False
    readonly: bool = False
    multiple: bool = False
    max_items: int | None = None
    disposition: str = "attachment"

    @property
    def capacity(self) -> int:
        return (self.max_items or DEFAULT_MAX_FILES) if self.multiple else 1

    def value(self, files: list[dict[str, Any]]) -> Any:
        """Record value holding `files`: a list for arrays, one entry or None otherwise."""
        return files if self.multiple else next(iter(files), None)

    def files(self, record: Mapping[str, Any]) -> list[dict[str, Any]]:
        value = record.get(self.name)
        return list(value) if isinstance(value, list) else [value] if value else []


@dataclass(frozen=True)
class FileMetadata:
    id: str
    name: str
    size: int
    content_type: str
    sha256: str
    store: str
    uploaded_at: datetime

    def to_record(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "size": self.size,
            "contentType": self.content_type,
            "sha256": self.sha256,
            "store": self.store,
            "uploadedAt": self.uploaded_at.isoformat(),
        }

    @classmethod
    def from_record(cls, value: Mapping[str, Any]) -> "FileMetadata":
        uploaded_at = value["uploadedAt"]
        return cls(
            id=value["id"],
            name=value["name"],
            size=value["size"],
            content_type=value["contentType"],
            sha256=value["sha256"],
            store=value["store"],
            uploaded_at=(
                uploaded_at
                if isinstance(uploaded_at, datetime)
                else datetime.fromisoformat(uploaded_at)
            ),
        )


class FileStore(Protocol):
    async def open(self) -> None: ...

    async def close(self) -> None: ...

    async def put(self, key: str, chunks: AsyncIterable[bytes]) -> None: ...

    def get(self, key: str) -> AsyncIterator[bytes]: ...

    async def delete(self, key: str) -> None: ...


def sniff(head: bytes, declared: str | None) -> str:
    """Effective content type of an upload starting with `head`; the declared type is only a hint for text."""
    try:
        if detected := puremagic.from_string(head, mime=True):
            return media_type(detected)
    except (puremagic.PureError, ValueError):
        pass
    return _textual_type(media_type(declared)) if _is_text(head) else "application/octet-stream"


def _is_text(head: bytes) -> bool:
    try:
        codecs.getincrementaldecoder("utf-8")().decode(head)
    except UnicodeDecodeError:
        return False
    return b"\x00" not in head


def _textual_type(declared: str) -> str:
    textual = (
        declared.startswith("text/")
        or declared in _TEXTUAL_TYPES
        or declared.endswith(_TEXTUAL_SUFFIXES)
    )
    return declared if textual else "text/plain"


def sanitize_filename(filename: str | None) -> str:
    basename = _PATH_SEPARATORS.split(filename or "")[-1]
    printable = "".join(char for char in basename if not unicodedata.category(char).startswith("C"))
    return printable[:MAX_NAME_LENGTH] or "file"


def content_disposition(disposition: str, filename: str) -> str:
    fallback = (
        filename.encode("ascii", "replace").decode("ascii").replace("\\", "_").replace('"', "_")
    )
    return f"{disposition}; filename=\"{fallback}\"; filename*=UTF-8''{quote(filename, safe='')}"


def served_disposition(disposition: str, content_type: str) -> str:
    """Inline only for types browsers render without executing active content."""
    safe = matches(content_type, _INLINE_TYPES) and not matches(content_type, _INLINE_EXCLUDED)
    return disposition if safe else "attachment"


class GuardedUpload:
    """Wraps one multipart part: sniffs, enforces size while streaming, hashes."""

    def __init__(self, part: "UploadPart", field: FileField) -> None:
        self.id = str(uuid7())
        self._part = part
        self._field = field
        self._digest = hashlib.sha256()
        self._size = 0
        self._content_type = "application/octet-stream"
        self._uploaded_at = datetime.now(UTC)

    async def __aiter__(self) -> AsyncIterator[bytes]:
        chunks = aiter(self._part.chunks)
        head = await self._head(chunks)
        self._admit(sniff(head, self._part.content_type))
        if head:
            yield self._count(head)
        async for chunk in chunks:
            yield self._count(chunk)

    @property
    def metadata(self) -> FileMetadata:
        return FileMetadata(
            id=self.id,
            name=sanitize_filename(self._part.filename),
            size=self._size,
            content_type=self._content_type,
            sha256=self._digest.hexdigest(),
            store=self._field.store,
            uploaded_at=self._uploaded_at,
        )

    @staticmethod
    async def _head(chunks: AsyncIterator[bytes]) -> bytes:
        head = bytearray()
        async for chunk in chunks:
            head += chunk
            if len(head) >= SNIFF_BYTES:
                break
        return bytes(head)

    def _admit(self, content_type: str) -> None:
        if not self._field.limits.accepts(content_type):
            raise UnsupportedFileTypeError(
                f"File type '{content_type}' is not allowed for '{self._field.name}'"
            )
        self._content_type = content_type

    def _count(self, chunk: bytes) -> bytes:
        self._size += len(chunk)
        if self._size > self._field.limits.max_size:
            raise FileTooLargeError(
                f"File for '{self._field.name}' exceeds {self._field.limits.max_size} bytes"
            )
        self._digest.update(chunk)
        return chunk


@dataclass(frozen=True)
class Ingest:
    data: dict[str, Any]
    files: dict[str, Any]
    stored: tuple[FileMetadata, ...]


@dataclass(frozen=True)
class Download:
    chunks: AsyncIterator[bytes]
    headers: dict[str, str]


class _Vault:
    """Bytes of one collection's files, addressed by metadata alone."""

    def __init__(self, collection: str, stores: Mapping[str, FileStore]) -> None:
        self._collection = collection
        self._stores = stores

    def _key(self, file_id: str) -> str:
        return f"{self._collection}/{file_id}"

    async def put(self, field: FileField, part: "UploadPart") -> FileMetadata:
        upload = GuardedUpload(part, field)
        await self._stores[field.store].put(self._key(upload.id), upload)
        return upload.metadata

    def get(self, metadata: FileMetadata) -> AsyncIterator[bytes]:
        return self._stores[metadata.store].get(self._key(metadata.id))

    async def discard(self, files: Iterable[FileMetadata]) -> None:
        for metadata in files:
            try:
                await self._stores[metadata.store].delete(self._key(metadata.id))
            except Exception:
                logger.exception("Could not delete stored file %s from '%s'", metadata.id, metadata.store)


class _Uploads:
    """Files stored during one request; all of them are discarded if the request fails."""

    def __init__(self, vault: _Vault) -> None:
        self._vault = vault
        self.received: defaultdict[str, list[FileMetadata]] = defaultdict(list)

    @property
    def stored(self) -> tuple[FileMetadata, ...]:
        return tuple(chain.from_iterable(self.received.values()))

    def records(self, field: str) -> list[dict[str, Any]]:
        return [metadata.to_record() for metadata in self.received[field]]

    async def add(self, field: FileField, part: "UploadPart", capacity: int) -> None:
        received = self.received[field.name]
        if len(received) >= capacity:
            raise InvalidUploadError(f"Too many files for '{field.name}' (at most {capacity})")
        received.append(await self._vault.put(field, part))

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, exc_type: type[BaseException] | None, *_: object) -> None:
        if exc_type is not None:
            await self._vault.discard(self.stored)


async def _read_data(part: "UploadPart") -> dict[str, Any]:
    body = bytearray()
    async for chunk in part.chunks:
        body += chunk
        if len(body) > DATA_PART_LIMIT:
            raise FileTooLargeError(f"The '{DATA_PART}' part exceeds {DATA_PART_LIMIT} bytes")
    try:
        data = json.loads(body)
    except ValueError as error:
        raise InvalidMultipartError(f"The '{DATA_PART}' part is not valid JSON") from error
    if not isinstance(data, dict):
        raise InvalidMultipartError(f"The '{DATA_PART}' part must be a JSON object")
    return data


class RecordFiles:
    def __init__(
        self,
        collection: str,
        fields: Mapping[str, FileField],
        stores: Mapping[str, FileStore],
    ) -> None:
        self._fields = fields
        self._vault = _Vault(collection, stores)

    @property
    def fields(self) -> Mapping[str, FileField]:
        return self._fields

    async def ingest_multipart(
        self, parts: AsyncIterator["UploadPart"], *, partial: bool
    ) -> Ingest:
        data: dict[str, Any] | None = None
        async with _Uploads(self._vault) as uploads:
            async for part in parts:
                if part.name != DATA_PART:
                    field = self._writable(part.name)
                    await uploads.add(field, part, field.capacity)
                elif data is None:
                    data = await _read_data(part)
                else:
                    raise InvalidUploadError(f"Duplicate '{DATA_PART}' part")
            files = self._complete(
                {name: self._fields[name].value(uploads.records(name)) for name in uploads.received},
                partial=partial,
            )
        return Ingest(data or {}, files, uploads.stored)

    def ingest_json(self, data: Mapping[str, Any], *, partial: bool) -> Ingest:
        if present := sorted(self._fields.keys() & data.keys()):
            raise InvalidUploadError(
                f"File fields {present} must be uploaded as multipart/form-data"
            )
        return Ingest(dict(data), self._complete({}, partial=partial), ())

    async def replace(
        self,
        record: Mapping[str, Any],
        field: str,
        parts: AsyncIterator["UploadPart"],
        file_id: str | None = None,
    ) -> tuple[Any, tuple[FileMetadata, ...]]:
        spec = self._writable(field)
        current = spec.files(record)
        if file_id is not None:
            self._select(current, file_id)
        async with _Uploads(self._vault) as uploads:
            async for part in parts:
                if part.name != field:
                    raise InvalidUploadError(f"Unexpected part '{part.name}'; expected '{field}'")
                await uploads.add(spec, part, 1 if file_id else spec.capacity)
            if not uploads.stored and (file_id or not spec.multiple or spec.required):
                raise MissingFileError(f"File for '{field}' is required")
        received = uploads.records(field)
        files = (
            [received[0] if item["id"] == file_id else item for item in current]
            if file_id
            else received
        )
        return spec.value(files), uploads.stored

    def remove(
        self, record: Mapping[str, Any], field: str, file_id: str | None = None
    ) -> Any:
        spec = self._writable(field)
        current = spec.files(record)
        kept = [item for item in current if file_id is not None and item["id"] != file_id]
        if len(kept) == len(current):
            raise StoredFileNotFoundError(f"No file to remove from '{field}'")
        if spec.required and not kept:
            raise MissingFileError(f"File for '{field}' is required")
        return spec.value(kept)

    def download(
        self, record: Mapping[str, Any], field: str, file_id: str | None = None
    ) -> Download:
        spec = self._field(field)
        metadata = FileMetadata.from_record(self._select(spec.files(record), file_id))
        return Download(
            chunks=self._vault.get(metadata),
            headers={
                "Content-Type": metadata.content_type,
                "Content-Length": str(metadata.size),
                "Content-Disposition": content_disposition(
                    served_disposition(spec.disposition, metadata.content_type), metadata.name
                ),
                "ETag": f'"{metadata.sha256}"',
                "X-Content-Type-Options": "nosniff",
                "Content-Security-Policy": "default-src 'none'; sandbox",
            },
        )

    def attached(self, record: Mapping[str, Any]) -> list[FileMetadata]:
        return [
            FileMetadata.from_record(item)
            for spec in self._fields.values()
            for item in spec.files(record)
        ]

    def orphaned(
        self, before: Mapping[str, Any], after: Mapping[str, Any]
    ) -> list[FileMetadata]:
        kept = {metadata.id for metadata in self.attached(after)}
        return [metadata for metadata in self.attached(before) if metadata.id not in kept]

    async def discard(self, files: Iterable[FileMetadata]) -> None:
        await self._vault.discard(files)

    def _field(self, name: str) -> FileField:
        if name not in self._fields:
            raise StoredFileNotFoundError(f"Unknown file field '{name}'")
        return self._fields[name]

    def _writable(self, name: str) -> FileField:
        spec = self._fields.get(name)
        if spec is None or spec.readonly:
            raise InvalidUploadError(f"Part '{name}' is not a writable file field")
        return spec

    def _complete(self, files: dict[str, Any], *, partial: bool) -> dict[str, Any]:
        """Full-record uploads must carry every required file; absent optional ones are empty."""
        if partial:
            return files
        absent = [spec for name, spec in self._fields.items() if not files.get(name)]
        if missing := [spec.name for spec in absent if spec.required and not spec.readonly]:
            raise MissingFileError(f"Required files missing: {missing}")
        return {**{spec.name: spec.value([]) for spec in absent}, **files}

    @staticmethod
    def _select(files: list[dict[str, Any]], file_id: str | None) -> dict[str, Any]:
        selected = next((item for item in files if file_id in (None, item["id"])), None)
        if selected is None:
            raise StoredFileNotFoundError(f"File '{file_id}' not found" if file_id else "No file stored")
        return selected
