"""Streaming multipart/form-data reader and the OpenAPI shapes of file endpoints."""

from collections.abc import AsyncIterable, AsyncIterator, Iterable
from dataclasses import dataclass, field
from typing import Any

from python_multipart.exceptions import FormParserError
from python_multipart.multipart import MultipartParser, parse_options_header

from .files import DATA_PART, FileField, InvalidMultipartError

FORM_DATA = b"multipart/form-data"
BINARY = {"type": "string", "contentMediaType": "application/octet-stream"}


@dataclass
class UploadPart:
    name: str
    filename: str | None
    content_type: str | None
    chunks: AsyncIterator[bytes]


def _media_type(content_type: str | None) -> tuple[bytes, dict[bytes, bytes]]:
    kind, options = parse_options_header(content_type)
    return kind.lower(), options


def is_multipart(content_type: str | None) -> bool:
    return _media_type(content_type)[0] == FORM_DATA


def read_multipart(content_type: str, body: AsyncIterable[bytes]) -> AsyncIterator[UploadPart]:
    kind, options = _media_type(content_type)
    if kind != FORM_DATA or not options.get(b"boundary"):
        raise InvalidMultipartError("Expected multipart/form-data with a boundary")
    return _MultipartStream(options[b"boundary"]).parts(body)


@dataclass
class _Headers:
    values: dict[bytes, bytes] = field(default_factory=dict)


_PART_END = object()


class _MultipartStream:
    """Push parser turning network chunks into parts whose data is streamed as it arrives."""

    def __init__(self, boundary: bytes) -> None:
        self._events: list[Any] = []
        self._headers = _Headers()
        self._header_name = bytearray()
        self._header_value = bytearray()
        self._complete = False
        self._parser = MultipartParser(
            boundary,
            callbacks={
                "on_part_begin": self._begin_part,
                "on_header_field": lambda data, start, end: self._header_name.extend(data[start:end]),
                "on_header_value": lambda data, start, end: self._header_value.extend(data[start:end]),
                "on_header_end": self._end_header,
                "on_headers_finished": lambda: self._events.append(self._headers),
                "on_part_data": self._data,
                "on_part_end": lambda: self._events.append(_PART_END),
                "on_end": self._end,
            },
        )

    async def parts(self, body: AsyncIterable[bytes]) -> AsyncIterator[UploadPart]:
        events = self._stream(body)
        async for event in events:
            if isinstance(event, _Headers):
                part = _part(event.values, _part_data(events))
                yield part
                async for _ in part.chunks:
                    pass

    async def _stream(self, body: AsyncIterable[bytes]) -> AsyncIterator[Any]:
        async for chunk in body:
            try:
                self._parser.write(chunk)
            except FormParserError as error:
                raise InvalidMultipartError(f"Malformed multipart body: {error}") from error
            events, self._events = self._events, []
            for event in events:
                yield event
        if not self._complete:
            raise InvalidMultipartError("Truncated multipart body")

    def _begin_part(self) -> None:
        self._headers = _Headers()

    def _end_header(self) -> None:
        self._headers.values[bytes(self._header_name).lower()] = bytes(self._header_value)
        self._header_name.clear()
        self._header_value.clear()

    def _data(self, data: bytes, start: int, end: int) -> None:
        if end > start:
            self._events.append(data[start:end])

    def _end(self) -> None:
        self._complete = True


async def _part_data(events: AsyncIterator[Any]) -> AsyncIterator[bytes]:
    async for event in events:
        if event is _PART_END:
            return
        yield event


def _part(headers: dict[bytes, bytes], chunks: AsyncIterator[bytes]) -> UploadPart:
    _, options = parse_options_header(headers.get(b"content-disposition"))
    if b"name" not in options:
        raise InvalidMultipartError("Multipart part without a name")
    filename = options.get(b"filename")
    content_type = headers.get(b"content-type")
    return UploadPart(
        name=_text(options[b"name"]),
        filename=None if filename is None else _text(filename),
        content_type=None if content_type is None else _text(content_type),
        chunks=chunks,
    )


def _text(value: bytes) -> str:
    return value.decode("utf-8", "replace")


def _file_schema(field: FileField, *, item: bool) -> dict[str, Any]:
    if item or not field.multiple:
        return BINARY
    return {"type": "array", "items": BINARY, "maxItems": field.capacity}


def _multipart_content(
    properties: dict[str, Any], required: Iterable[str], encoding: dict[str, Any] | None = None
) -> dict[str, Any]:
    schema = {"type": "object", "properties": properties}
    content = {"schema": schema | ({"required": names} if (names := list(required)) else {})}
    return content | ({"encoding": encoding} if encoding else {})


def multipart_request_body(
    data_schema: dict[str, Any], fields: Iterable[FileField], *, partial: bool
) -> dict[str, Any]:
    """Readonly file fields are left out: they are never uploaded."""
    fields = [spec for spec in fields if not spec.readonly]
    return {
        "required": True,
        "content": {
            "multipart/form-data": _multipart_content(
                {DATA_PART: data_schema} | {spec.name: _file_schema(spec, item=False) for spec in fields},
                () if partial else (spec.name for spec in fields if spec.required),
                {DATA_PART: {"contentType": "application/json"}},
            ),
            "application/json": {"schema": data_schema},
        },
    }


def file_upload_body(field: FileField, *, item: bool) -> dict[str, Any]:
    required = item or not field.multiple or field.required
    return {
        "required": True,
        "content": {
            "multipart/form-data": _multipart_content(
                {field.name: _file_schema(field, item=item)}, (field.name,) if required else ()
            )
        },
    }


def file_download_responses() -> dict[str, Any]:
    return {
        "200": {"description": "File content", "content": {"*/*": {"schema": BINARY}}},
        "404": {"description": "File not found"},
    }
