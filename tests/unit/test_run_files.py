"""`stackform run` serves file fields over HTTP against a real filesystem store."""

import json
import textwrap
from pathlib import Path

import httpx
import pytest

from yaml_api_generator.runtime.multipart import BINARY
from yaml_api_generator.server import build_app

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00" + b"\x00" * 64
PDF = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF\n"

_SPEC = """
    version: "0.3"
    api: {{ basePath: "" }}
    datastores:
      main: {{ type: postgres, dsn: "postgresql+asyncpg://localhost/unused", default: true }}
      disk: {{ type: filesystem, path: "{uploads}", default: true }}
    entities:
      post:
        fields:
          id: {{ type: id, format: uuidv4 }}
          title: {{ type: string, required: true }}
          cover: {{ type: file, required: true, maxSize: 1KB, types: [image/png, image/jpeg], disposition: inline }}
          attachments: {{ type: array, maxItems: 2, items: {{ type: file, types: [application/pdf] }} }}
    repositories:
      posts: {{ entity: post }}
    services:
      posts: {{ repository: posts }}
    controllers:
      posts:
        base_path: /posts
        routes:
          create: {{ service: posts, method: POST, path: "", access: public }}
          get: {{ service: posts, method: GET, path: "/{{id}}", access: public }}
          update: {{ service: posts, method: PATCH, path: "/{{id}}", access: public }}
          replace: {{ service: posts, method: PUT, path: "/{{id}}", access: public }}
          delete: {{ service: posts, method: DELETE, path: "/{{id}}", access: public }}
"""


@pytest.fixture
def uploads(tmp_path) -> Path:
    return tmp_path / "uploads"


@pytest.fixture
async def client(tmp_path, uploads, monkeypatch):
    monkeypatch.setenv("YAML_API_DB_MAIN_DSN", f"sqlite+aiosqlite:///{tmp_path / 'db.sqlite'}")
    spec = tmp_path / "spec.yaml"
    spec.write_text(textwrap.dedent(_SPEC.format(uploads=uploads)))
    app = build_app(str(spec))
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
            yield http


def _data(**fields) -> tuple[None, str, str]:
    return None, json.dumps(fields), "application/json"


def _stored(uploads: Path) -> list[Path]:
    return sorted(path for path in uploads.rglob("*") if path.is_file() and ".tmp" not in path.parts)


async def _create(client, *attachments: bytes) -> dict:
    files = [
        ("_data", _data(title="Hello")),
        ("cover", ("cover.png", PNG, "image/png")),
        *[("attachments", (f"doc{i}.pdf", pdf, "application/pdf")) for i, pdf in enumerate(attachments)],
    ]
    response = await client.post("/posts", files=files)
    assert response.status_code == 200, response.text
    return response.json()


async def test_multipart_create_stores_file_and_returns_metadata(client, uploads):
    post = await _create(client, PDF)

    assert post["title"] == "Hello"
    assert post["cover"]["name"] == "cover.png"
    assert post["cover"]["size"] == len(PNG)
    assert post["cover"]["contentType"] == "image/png"
    assert set(post["cover"]) == {"id", "name", "size", "contentType", "sha256", "store", "uploadedAt"}
    assert [item["name"] for item in post["attachments"]] == ["doc0.pdf"]
    assert len(_stored(uploads)) == 2


async def test_json_create_without_required_file_is_rejected(client, uploads):
    response = await client.post("/posts", json={"title": "Hello"})

    assert response.status_code == 422
    assert _stored(uploads) == []


async def test_json_create_with_file_keys_is_rejected(client):
    response = await client.post("/posts", json={"title": "Hello", "cover": {"id": "x"}})

    assert response.status_code == 422


async def test_invalid_data_part_discards_stored_files(client, uploads):
    response = await client.post(
        "/posts",
        files=[("_data", _data()), ("cover", ("cover.png", PNG, "image/png"))],
    )

    assert response.status_code == 422
    assert _stored(uploads) == []


async def test_oversized_file_is_rejected_without_leftovers(client, uploads):
    response = await client.post(
        "/posts",
        files=[("_data", _data(title="Big")), ("cover", ("big.png", PNG * 32, "image/png"))],
    )

    assert response.status_code == 413
    assert _stored(uploads) == []


async def test_sniffed_type_overrides_declared_content_type(client, uploads):
    response = await client.post(
        "/posts",
        files=[("_data", _data(title="Fake")), ("cover", ("cover.png", PDF, "image/png"))],
    )

    assert response.status_code == 415
    assert _stored(uploads) == []


async def test_download_streams_bytes_with_headers(client):
    post = await _create(client, PDF)

    cover = await client.get(f"/posts/{post['id']}/files/cover")
    item_id = post["attachments"][0]["id"]
    attachment = await client.get(f"/posts/{post['id']}/files/attachments/{item_id}")

    assert cover.status_code == 200
    assert cover.content == PNG
    assert cover.headers["content-type"] == "image/png"
    assert cover.headers["content-disposition"].startswith("inline")
    assert attachment.content == PDF
    assert attachment.headers["content-disposition"].startswith("attachment")


async def test_download_unknown_record_or_item_is_404(client):
    post = await _create(client)

    assert (await client.get("/posts/missing/files/cover")).status_code == 404
    assert (await client.get(f"/posts/{post['id']}/files/attachments/missing")).status_code == 404


async def test_replace_file_swaps_bytes_and_discards_old(client, uploads):
    post = await _create(client)

    response = await client.put(
        f"/posts/{post['id']}/files/cover",
        files=[("cover", ("new.jpg", JPEG, "image/jpeg"))],
    )

    assert response.status_code == 200, response.text
    assert response.json()["cover"]["name"] == "new.jpg"
    assert response.json()["title"] == "Hello"
    assert (await client.get(f"/posts/{post['id']}/files/cover")).content == JPEG
    assert len(_stored(uploads)) == 1


async def test_replace_array_item_keeps_position(client, uploads):
    post = await _create(client, PDF, PDF)
    first, second = (item["id"] for item in post["attachments"])

    response = await client.put(
        f"/posts/{post['id']}/files/attachments/{first}",
        files=[("attachments", ("swap.pdf", PDF, "application/pdf"))],
    )

    names = [item["name"] for item in response.json()["attachments"]]
    assert response.status_code == 200, response.text
    assert names == ["swap.pdf", "doc1.pdf"]
    assert response.json()["attachments"][1]["id"] == second
    assert len(_stored(uploads)) == 3


async def test_remove_array_item_deletes_its_bytes(client, uploads):
    post = await _create(client, PDF, PDF)
    first, second = (item["id"] for item in post["attachments"])

    response = await client.delete(f"/posts/{post['id']}/files/attachments/{first}")

    assert response.status_code == 200, response.text
    assert [item["id"] for item in response.json()["attachments"]] == [second]
    assert len(_stored(uploads)) == 2


async def test_remove_required_file_is_rejected(client):
    post = await _create(client)

    response = await client.delete(f"/posts/{post['id']}/files/cover")

    assert response.status_code == 422


async def test_patch_with_file_part_replaces_field(client, uploads):
    post = await _create(client, PDF)

    response = await client.patch(
        f"/posts/{post['id']}",
        files=[("_data", _data(title="Renamed")), ("cover", ("next.jpg", JPEG, "image/jpeg"))],
    )

    body = response.json()
    assert response.status_code == 200, response.text
    assert body["title"] == "Renamed"
    assert body["cover"]["name"] == "next.jpg"
    assert body["attachments"] == post["attachments"]
    assert len(_stored(uploads)) == 2


async def test_json_patch_keeps_files(client):
    post = await _create(client)

    response = await client.patch(f"/posts/{post['id']}", json={"title": "Plain"})

    assert response.status_code == 200, response.text
    assert response.json()["cover"] == post["cover"]


async def test_put_record_carries_file_metadata_over(client, uploads):
    post = await _create(client, PDF)

    response = await client.put(f"/posts/{post['id']}", json={"title": "Replaced"})

    body = response.json()
    assert response.status_code == 200, response.text
    assert body["title"] == "Replaced"
    assert body["cover"] == post["cover"]
    assert body["attachments"] == post["attachments"]
    assert len(_stored(uploads)) == 2


async def test_put_record_rejects_multipart(client):
    post = await _create(client)

    response = await client.put(
        f"/posts/{post['id']}",
        files=[("_data", _data(title="X")), ("cover", ("c.png", PNG, "image/png"))],
    )

    assert response.status_code in {400, 415, 422}


async def test_record_delete_removes_files_from_disk(client, uploads):
    post = await _create(client, PDF)

    response = await client.delete(f"/posts/{post['id']}")

    assert response.status_code == 200, response.text
    assert _stored(uploads) == []


async def test_openapi_documents_multipart_and_binary(client):
    spec = (await client.get("/openapi.json")).json()
    paths = spec["paths"]

    create = paths["/posts"]["post"]["requestBody"]["content"]
    multipart = create["multipart/form-data"]["schema"]
    assert "application/json" in create
    assert multipart["properties"]["cover"] == BINARY
    assert "cover" in multipart["required"]

    patch = paths["/posts/{id}"]["patch"]["requestBody"]["content"]["multipart/form-data"]["schema"]
    assert "cover" not in patch.get("required", [])

    download = paths["/posts/{id}/files/cover"]["get"]["responses"]["200"]["content"]
    assert download["*/*"]["schema"] == BINARY
    assert "multipart/form-data" in paths["/posts/{id}/files/cover"]["put"]["requestBody"]["content"]
    assert "delete" in paths["/posts/{id}/files/attachments/{fileId}"]
