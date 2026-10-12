"""`stackform run` uploads to and downloads from a real MinIO bucket."""

import textwrap
from uuid import uuid4

import httpx
import pytest

from yaml_api_generator.server import build_app

pytestmark = pytest.mark.integration

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64

_SPEC = """
    version: "0.3"
    api: {{ basePath: "" }}
    datastores:
      main: {{ type: postgres, dsn: "postgresql+asyncpg://localhost/unused", default: true }}
      media:
        type: s3
        bucket: {bucket}
        endpoint: {endpoint}
        region: us-east-1
        accessKey: minioadmin
        secretKey: minioadmin
        default: true
    entities:
      post:
        fields:
          id: {{ type: id, format: uuidv4 }}
          cover: {{ type: file, required: true, types: [image/png] }}
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
          delete: {{ service: posts, method: DELETE, path: "/{{id}}", access: public }}
"""


@pytest.fixture
async def client(tmp_path, monkeypatch, s3_endpoint):
    monkeypatch.setenv("YAML_API_DB_MAIN_DSN", f"sqlite+aiosqlite:///{tmp_path / 'db.sqlite'}")
    spec = tmp_path / "spec.yaml"
    spec.write_text(textwrap.dedent(_SPEC.format(bucket=f"run-{uuid4().hex[:12]}", endpoint=s3_endpoint)))
    app = build_app(str(spec))
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
            yield http


async def test_s3_upload_download_and_delete(client):
    created = await client.post("/posts", files=[("cover", ("c.png", PNG, "image/png"))])
    assert created.status_code == 200, created.text
    post_id = created.json()["id"]

    download = await client.get(f"/posts/{post_id}/files/cover")
    assert download.content == PNG
    assert download.headers["content-type"] == "image/png"

    assert (await client.delete(f"/posts/{post_id}")).status_code == 200
    assert (await client.get(f"/posts/{post_id}/files/cover")).status_code == 404
