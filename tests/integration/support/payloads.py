"""Real file bytes and the multipart parts that carry them."""

import json
from uuid import uuid4

KB = 1024
PNG, JPEG, PDF = "image/png", "image/jpeg", "application/pdf"

_SIGNATURES = {
    PNG: b"\x89PNG\r\n\x1a\n",
    JPEG: b"\xff\xd8\xff\xe0\x00\x10JFIF\x00",
    PDF: b"%PDF-1.4\n",
}

Part = tuple[str, tuple]


def content(content_type: str, size: int = 96) -> bytes:
    """Unique `size` bytes whose signature makes them sniff as `content_type`."""
    signature = _SIGNATURES[content_type]
    return (signature + uuid4().hex.encode() * size)[:size]


def record(**fields) -> Part:
    return "_data", (None, json.dumps(fields), "application/json")


def upload(field: str, body: bytes, content_type: str, filename: str | None = None) -> Part:
    return field, (filename or f"{field}.bin", body, content_type)


def document(*files: Part, owner: str = "alice") -> list[Part]:
    """The parts of a valid document create: its record fields, a cover unless `files` bring one, then `files`."""
    cover = [] if any(name == "cover" for name, _ in files) else [upload("cover", content(PNG), PNG, "cover.png")]
    return [record(ownerId=owner, title="Report"), *cover, *files]


def asset(*files: Part) -> list[Part]:
    return [record(label="Asset"), *files]
