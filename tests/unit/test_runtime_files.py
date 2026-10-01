import hashlib
import json
from datetime import UTC, datetime

import pytest

from yaml_api_generator.runtime.files import (
    DATA_PART_LIMIT,
    FileField,
    FileLimits,
    FileMetadata,
    FileTooLargeError,
    GuardedUpload,
    InvalidMultipartError,
    InvalidUploadError,
    MissingFileError,
    RecordFiles,
    StoredFileNotFoundError,
    UnsupportedFileTypeError,
    content_disposition,
    sniff,
)
from yaml_api_generator.runtime.filesystem_store import FilesystemStore
from yaml_api_generator.runtime.multipart import UploadPart

PNG = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR" + bytes(range(256)) * 64
JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01" + b"\x00" * 4000
PDF = b"%PDF-1.4\n" + b"1 0 obj << >> endobj\n" * 500

COVER = FileField(
    "cover",
    "disk",
    FileLimits(max_size=64 * 1024, types=("image/*",)),
    required=True,
    disposition="inline",
)
GALLERY = FileField("gallery", "disk", FileLimits(types=("application/pdf",)), multiple=True, max_items=2)
AVATAR = FileField("avatar", "disk", readonly=True)
FIELDS = {spec.name: spec for spec in (COVER, GALLERY, AVATAR)}


async def chunks(payload: bytes, size: int = 1000):
    for start in range(0, len(payload), size):
        yield payload[start : start + size]


def part(name: str, payload: bytes, filename: str = "upload.bin", content_type: str | None = None) -> UploadPart:
    return UploadPart(name, filename, content_type, chunks(payload))


def data(value) -> UploadPart:
    return UploadPart("_data", None, "application/json", chunks(json.dumps(value).encode()))


async def parts(*items: UploadPart):
    for item in items:
        yield item


@pytest.fixture
async def root(tmp_path):
    return tmp_path / "files"


@pytest.fixture
async def files(root):
    store = FilesystemStore(root)
    await store.open()
    yield RecordFiles("posts", FIELDS, {"disk": store})
    await store.close()


def stored(root) -> list[str]:
    return sorted(path.name for path in root.rglob("*") if path.is_file())


async def download(files: RecordFiles, record, field, file_id=None) -> tuple[bytes, dict[str, str]]:
    result = files.download(record, field, file_id)
    return b"".join([chunk async for chunk in result.chunks]), result.headers


@pytest.mark.parametrize(
    ("types", "content_type", "accepted"),
    [
        ((), "application/x-anything", True),
        (("image/*",), "image/png", True),
        (("image/*",), "IMAGE/PNG; charset=binary", True),
        (("image/*",), "imagex/png", False),
        (("image/png", "application/pdf"), "application/pdf", True),
        (("image/png",), "image/jpeg", False),
    ],
)
def test_limits_accept_exact_types_and_subtype_wildcards(types, content_type, accepted):
    assert FileLimits(types=types).accepts(content_type) is accepted


@pytest.mark.parametrize(
    ("head", "declared", "expected"),
    [
        (PNG, "application/pdf", "image/png"),
        (JPEG, None, "image/jpeg"),
        (PDF, "image/png", "application/pdf"),
        (b"plain words", "text/csv", "text/csv"),
        (b'{"a": 1}', "application/json", "application/json"),
        (b"<a/>", "application/atom+xml", "application/atom+xml"),
        (b"plain words", "image/png", "text/plain"),
        (b"plain words", None, "text/plain"),
        ("olá mundo".encode()[:-1] + b"\xc3", "text/plain; charset=utf-8", "text/plain"),
        (b"\x00\x01\x02\x03binary", "text/plain", "application/octet-stream"),
        (b"\x80\x81\x82 not utf-8", "text/plain", "application/octet-stream"),
    ],
)
def test_sniff_trusts_content_over_the_declared_type(head, declared, expected):
    assert sniff(head, declared) == expected


def test_content_disposition_encodes_unicode_names():
    assert content_disposition("attachment", 'relatório "final".pdf') == (
        'attachment; filename="relat?rio _final_.pdf"; '
        "filename*=UTF-8''relat%C3%B3rio%20%22final%22.pdf"
    )


async def test_guarded_upload_hashes_and_measures_the_stream():
    upload = GuardedUpload(part("cover", PNG, "../../etc/pic\x00.png", "image/png"), COVER)

    received = b"".join([chunk async for chunk in upload])

    assert received == PNG
    metadata = upload.metadata
    assert (metadata.id, metadata.name, metadata.size) == (upload.id, "pic.png", len(PNG))
    assert metadata.sha256 == hashlib.sha256(PNG).hexdigest()
    assert (metadata.content_type, metadata.store) == ("image/png", "disk")


async def test_guarded_upload_stops_reading_as_soon_as_the_limit_is_exceeded():
    consumed = 0

    async def endless():
        nonlocal consumed
        yield PNG[:1024]
        while True:
            consumed += 1024
            yield b"\x00" * 1024

    upload = GuardedUpload(UploadPart("cover", "big.png", None, endless()), COVER)
    received = 0
    with pytest.raises(FileTooLargeError):
        async for chunk in upload:
            received += len(chunk)

    assert received <= COVER.limits.max_size
    assert consumed <= COVER.limits.max_size + 2048


async def test_create_stores_bytes_and_returns_record_ready_metadata(files, root):
    ingest = await files.ingest_multipart(
        parts(
            data({"title": "hello"}),
            part("cover", PNG, "cover.png", "image/png"),
            part("gallery", PDF, "a.pdf"),
            part("gallery", PDF[:100], "b.pdf"),
        ),
        partial=False,
    )

    assert ingest.data == {"title": "hello"}
    assert [item["name"] for item in ingest.files["gallery"]] == ["a.pdf", "b.pdf"]
    assert ingest.files["avatar"] is None
    cover = ingest.files["cover"]
    assert set(cover) == {"id", "name", "size", "contentType", "sha256", "store", "uploadedAt"}
    assert (cover["contentType"], cover["size"]) == ("image/png", len(PNG))
    assert FileMetadata.from_record(cover) in ingest.stored
    assert stored(root) == sorted(metadata.id for metadata in ingest.stored)

    body, headers = await download(files, ingest.files, "cover")
    assert body == PNG
    assert headers["Content-Length"] == str(len(PNG))


async def test_create_without_a_required_file_fails_and_keeps_nothing(files, root):
    with pytest.raises(MissingFileError):
        await files.ingest_multipart(parts(part("gallery", PDF, "a.pdf")), partial=False)

    assert stored(root) == []


async def test_partial_update_only_returns_uploaded_fields(files):
    ingest = await files.ingest_multipart(parts(part("gallery", PDF)), partial=True)

    assert list(ingest.files) == ["gallery"]
    assert ingest.data == {}


@pytest.mark.parametrize(
    ("upload", "error"),
    [
        ([part("cover", PDF, "fake.png", "image/png")], UnsupportedFileTypeError),
        ([part("cover", PNG * 20, "huge.png", "image/png")], FileTooLargeError),
        ([part("title", b"hello")], InvalidUploadError),
        ([part("avatar", PNG)], InvalidUploadError),
        ([UploadPart("_data", None, None, chunks(b"{not json"))], InvalidMultipartError),
        ([UploadPart("_data", None, None, chunks(b"[1, 2]"))], InvalidMultipartError),
        ([UploadPart("_data", None, None, chunks(b" " * (DATA_PART_LIMIT + 1)))], FileTooLargeError),
        ([data({}), data({})], InvalidUploadError),
        ([part("gallery", PDF)], InvalidUploadError),
        ([part("cover", PNG), part("cover", PNG)], InvalidUploadError),
    ],
)
async def test_any_rejected_part_rolls_back_files_already_stored(files, root, upload, error):
    with pytest.raises(error) as raised:
        await files.ingest_multipart(
            parts(part("gallery", PDF), part("gallery", PDF), *upload),
            partial=False,
        )

    assert raised.value.status_code == error.status_code
    assert stored(root) == []


def test_json_bodies_cannot_carry_files(files):
    with pytest.raises(InvalidUploadError):
        files.ingest_json({"title": "x", "cover": {"id": "forged"}}, partial=True)
    with pytest.raises(MissingFileError):
        files.ingest_json({"title": "x"}, partial=False)

    assert files.ingest_json({"title": "x"}, partial=True).files == {}


@pytest.fixture
async def record(files):
    ingest = await files.ingest_multipart(
        parts(part("cover", PNG, "cover.png"), part("gallery", PDF, "a.pdf"), part("gallery", PDF[:50], "b.pdf")),
        partial=False,
    )
    return {"id": "p1", "title": "hello", **ingest.files}


async def test_replace_single_file_keeps_old_bytes_until_discarded(files, root, record):
    value, new = await files.replace(record, "cover", parts(part("cover", JPEG, "new.jpg")))
    updated = {**record, "cover": value}

    assert value["contentType"] == "image/jpeg"
    assert (await download(files, updated, "cover"))[0] == JPEG
    assert record["cover"]["id"] in stored(root)

    await files.discard(files.orphaned(record, updated))

    assert record["cover"]["id"] not in stored(root)
    assert new[0].id in stored(root)


async def test_replace_one_array_item_keeps_its_position(files, record):
    first, second = record["gallery"]

    value, _ = await files.replace(record, "gallery", parts(part("gallery", PDF[:20], "c.pdf")), second["id"])

    assert [item["name"] for item in value] == ["a.pdf", "c.pdf"]
    assert value[0] == first


async def test_replace_whole_array(files, record):
    value, stored_files = await files.replace(record, "gallery", parts(part("gallery", PDF, "z.pdf")))

    assert [item["name"] for item in value] == ["z.pdf"]
    assert len(stored_files) == 1
    assert (await files.replace(record, "gallery", parts()))[0] == []


@pytest.mark.parametrize(
    ("field", "upload", "file_id", "error"),
    [
        ("cover", [], None, MissingFileError),
        ("cover", [part("cover", PNG), part("cover", PNG)], None, InvalidUploadError),
        ("gallery", [part("gallery", PDF) for _ in range(3)], None, InvalidUploadError),
        ("gallery", [part("gallery", PDF)], "unknown", StoredFileNotFoundError),
        ("gallery", [part("cover", PDF)], None, InvalidUploadError),
        ("gallery", [part("gallery", PNG)], None, UnsupportedFileTypeError),
        ("avatar", [part("avatar", PNG)], None, InvalidUploadError),
    ],
)
async def test_rejected_replacements_store_nothing(files, root, record, field, upload, file_id, error):
    before = stored(root)

    with pytest.raises(error):
        await files.replace(record, field, parts(*upload), file_id)

    assert stored(root) == before


def test_remove(files, record):
    first, second = record["gallery"]

    assert files.remove(record, "gallery", first["id"]) == [second]
    with pytest.raises(MissingFileError):
        files.remove(record, "cover")
    with pytest.raises(StoredFileNotFoundError):
        files.remove(record, "gallery", "unknown")
    with pytest.raises(StoredFileNotFoundError):
        files.remove({**record, "gallery": []}, "gallery")


def test_removing_the_last_item_of_a_required_array_is_rejected(root):
    required = FileField("gallery", "disk", multiple=True, required=True)
    only = {"id": "f1"}
    files = RecordFiles("posts", {"gallery": required}, {})

    with pytest.raises(MissingFileError):
        files.remove({"gallery": [only]}, "gallery", "f1")


async def test_download_headers(files, record):
    body, headers = await download(files, record, "gallery", record["gallery"][1]["id"])

    assert body == PDF[:50]
    assert headers == {
        "Content-Type": "application/pdf",
        "Content-Length": "50",
        "Content-Disposition": "attachment; filename=\"b.pdf\"; filename*=UTF-8''b.pdf",
        "ETag": f'"{hashlib.sha256(PDF[:50]).hexdigest()}"',
        "X-Content-Type-Options": "nosniff",
        "Content-Security-Policy": "default-src 'none'; sandbox",
    }
    assert (await download(files, record, "cover"))[1]["Content-Disposition"].startswith("inline;")


async def test_inline_is_downgraded_for_active_content(root):
    store = FilesystemStore(root)
    await store.open()
    page = FileField("page", "disk", disposition="inline")
    files = RecordFiles("posts", {"page": page}, {"disk": store})
    svg = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'

    ingest = await files.ingest_multipart(parts(part("page", svg, "x.svg", "image/svg+xml")), partial=True)

    assert ingest.files["page"]["contentType"] == "image/svg+xml"
    assert (await download(files, ingest.files, "page"))[1]["Content-Disposition"].startswith("attachment;")


def test_download_of_an_empty_field_or_unknown_item_is_not_found(files, record):
    with pytest.raises(StoredFileNotFoundError):
        files.download({**record, "cover": None}, "cover")
    with pytest.raises(StoredFileNotFoundError):
        files.download(record, "gallery", "unknown")
    with pytest.raises(StoredFileNotFoundError):
        files.download(record, "title")


async def test_deleting_a_record_discards_all_its_files(files, root, record):
    attached = files.attached(record)

    await files.discard(attached)
    await files.discard(attached)

    assert len(attached) == 3
    assert stored(root) == []


async def test_discard_never_raises(files):
    ghost = FileMetadata("ghost", "x", 1, "text/plain", "0", "missing-store", datetime.now(UTC))

    await files.discard([ghost])


def test_metadata_round_trips_through_records():
    metadata = FileMetadata("f1", "a.pdf", 3, "application/pdf", "ab", "disk", datetime(2026, 1, 2, tzinfo=UTC))

    assert FileMetadata.from_record(metadata.to_record()) == metadata
    assert FileMetadata.from_record({**metadata.to_record(), "uploadedAt": metadata.uploaded_at}) == metadata
