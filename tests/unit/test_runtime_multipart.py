import json

import pytest

from yaml_api_generator.runtime.files import FileField, InvalidMultipartError
from yaml_api_generator.runtime.multipart import (
    file_download_responses,
    file_upload_body,
    is_multipart,
    multipart_request_body,
    read_multipart,
)

BOUNDARY = "test-boundary-7MA4YWxkTrZu0gW"
CONTENT_TYPE = f"multipart/form-data; boundary={BOUNDARY}"


def encode(*parts: tuple[str, bytes, dict[str, str]]) -> bytes:
    body = bytearray()
    for name, content, extra in parts:
        disposition = f'form-data; name="{name}"'
        if "filename" in extra:
            disposition += f'; filename="{extra["filename"]}"'
        body += f"--{BOUNDARY}\r\nContent-Disposition: {disposition}\r\n".encode()
        if "type" in extra:
            body += f"Content-Type: {extra['type']}\r\n".encode()
        body += b"\r\n" + content + b"\r\n"
    return bytes(body + f"--{BOUNDARY}--\r\n".encode())


async def chunked(body: bytes, size: int):
    for start in range(0, len(body), size):
        yield body[start : start + size]


async def collect(content_type: str, body: bytes, size: int = 7) -> list[tuple]:
    return [
        (part.name, part.filename, part.content_type, b"".join([chunk async for chunk in part.chunks]))
        async for part in read_multipart(content_type, chunked(body, size))
    ]


@pytest.mark.parametrize("size", [1, 7, 64, 100_000])
async def test_parts_are_streamed_whatever_the_network_chunking(size):
    payload = bytes(range(256)) * 300
    body = encode(
        ("_data", b'{"title": "hello"}', {}),
        ("cover", payload, {"filename": "cover.png", "type": "image/png"}),
        ("notes", b"", {"filename": "empty.txt"}),
    )

    assert await collect(CONTENT_TYPE, body, size) == [
        ("_data", None, None, b'{"title": "hello"}'),
        ("cover", "cover.png", "image/png", payload),
        ("notes", "empty.txt", None, b""),
    ]


async def test_part_data_is_never_buffered_beyond_one_network_chunk():
    payload = b"x" * 50_000
    body = encode(("file", payload, {"filename": "a.bin"}))

    sizes = [
        len(chunk)
        async for part in read_multipart(CONTENT_TYPE, chunked(body, 1024))
        async for chunk in part.chunks
    ]

    assert sum(sizes) == len(payload)
    assert max(sizes) <= 1024


async def test_unconsumed_parts_are_skipped():
    body = encode(("first", b"a" * 5000, {"filename": "a"}), ("second", b"b", {"filename": "b"}))

    names = [part.name async for part in read_multipart(CONTENT_TYPE, chunked(body, 100))]

    assert names == ["first", "second"]


async def test_utf8_filenames_are_decoded():
    body = encode(("file", b"x", {"filename": "relatório.pdf"}))

    assert (await collect(CONTENT_TYPE, body))[0][1] == "relatório.pdf"


@pytest.mark.parametrize(
    "content_type",
    ["application/json", "multipart/form-data", "multipart/mixed; boundary=abc"],
)
def test_non_form_data_or_missing_boundary_is_rejected(content_type):
    with pytest.raises(InvalidMultipartError):
        read_multipart(content_type, chunked(b"", 1))


async def test_truncated_body_is_rejected():
    body = encode(("file", b"payload", {"filename": "a"}))

    with pytest.raises(InvalidMultipartError):
        await collect(CONTENT_TYPE, body[:-20])


async def test_garbage_body_is_rejected():
    with pytest.raises(InvalidMultipartError):
        await collect(CONTENT_TYPE, b"this is not multipart at all")


async def test_part_without_name_is_rejected():
    body = f"--{BOUNDARY}\r\nContent-Disposition: form-data\r\n\r\nx\r\n--{BOUNDARY}--\r\n".encode()

    with pytest.raises(InvalidMultipartError):
        await collect(CONTENT_TYPE, body)


@pytest.mark.parametrize(
    ("content_type", "expected"),
    [
        (CONTENT_TYPE, True),
        ("Multipart/Form-Data; boundary=x", True),
        ("application/json", False),
        (None, False),
    ],
)
def test_is_multipart(content_type, expected):
    assert is_multipart(content_type) is expected


BINARY = {"type": "string", "contentMediaType": "application/octet-stream"}
COVER = FileField("cover", "disk", required=True)
GALLERY = FileField("gallery", "disk", multiple=True, max_items=3)
DATA = {"$ref": "#/components/schemas/PostCreate"}


def test_create_body_offers_multipart_and_json():
    body = multipart_request_body(DATA, [COVER, GALLERY], partial=False)
    form = body["content"]["multipart/form-data"]

    assert form["schema"] == {
        "type": "object",
        "properties": {
            "_data": DATA,
            "cover": BINARY,
            "gallery": {"type": "array", "items": BINARY, "maxItems": 3},
        },
        "required": ["cover"],
    }
    assert form["encoding"] == {"_data": {"contentType": "application/json"}}
    assert body["content"]["application/json"] == {"schema": DATA}
    json.dumps(body)


def test_partial_body_requires_no_file():
    body = multipart_request_body(DATA, [COVER], partial=True)

    assert "required" not in body["content"]["multipart/form-data"]["schema"]


@pytest.mark.parametrize(
    ("field", "item", "schema", "required"),
    [
        (COVER, False, BINARY, ["cover"]),
        (GALLERY, False, {"type": "array", "items": BINARY, "maxItems": 3}, None),
        (GALLERY, True, BINARY, ["gallery"]),
    ],
)
def test_file_upload_body(field, item, schema, required):
    form = file_upload_body(field, item=item)["content"]["multipart/form-data"]["schema"]

    assert form["properties"] == {field.name: schema}
    assert form.get("required") == required


def test_download_responses_are_binary():
    responses = file_download_responses()

    assert responses["200"]["content"] == {"*/*": {"schema": BINARY}}
    assert "404" in responses
