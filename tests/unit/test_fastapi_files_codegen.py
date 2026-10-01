"""FastAPI codegen for file fields: emitted artifacts, then the generated app serving real uploads over HTTP."""

import compileall
import os
import subprocess
import sys
import textwrap

import pytest

from yaml_api_generator.cli.compiler import compile_project

_ROUTES = """
controllers:
  documents:
    base_path: /documents
    routes:
      create:  { service: documents, method: POST, path: "", access: public }
      list:    { service: documents, method: GET, path: "", access: public }
      get:     { service: documents, method: GET, path: "/{id}", access: public }
      update:  { service: documents, method: PATCH, path: "/{id}", access: public }
      replace: { service: documents, method: PUT, path: "/{id}", access: public }
      delete:  { service: documents, method: DELETE, path: "/{id}", access: public }
"""

_FILESYSTEM_SPEC = """
version: "0.3"
api: { basePath: /api, version: v1 }
datastores:
  store: { type: postgres, dsn: "postgresql+asyncpg://localhost/docs", default: true }
  uploads: { type: filesystem, path: ./data/uploads }
entities:
  document:
    fields:
      id: { type: id }
      title: { type: string, required: true }
      cover: { type: file, required: true, maxSize: 1KB, types: ["image/*"], disposition: inline }
      attachments: { type: array, items: { type: file, types: ["application/pdf"] }, maxItems: 2 }
  tag:
    fields:
      id: { type: id }
      label: { type: string, required: true }
repositories:
  documents: { entity: document, files: uploads }
  tags: { entity: tag }
services:
  documents: { repository: documents }
  tags: { repository: tags }
""" + _ROUTES + """
  tags:
    base_path: /tags
    routes:
      create: { service: tags, method: POST, path: "", access: public }
      get:    { service: tags, method: GET, path: "/{id}", access: public }
"""

_S3_SPEC = """
version: "0.3"
api: { basePath: /api, version: v1 }
datastores:
  store: { type: postgres, dsn: "postgresql+asyncpg://localhost/docs", default: true }
  media: { type: s3, bucket: docs, endpoint: "http://localhost:9000", accessKey: spec-access, secretKey: spec-secret }
entities:
  document:
    fields:
      id: { type: id }
      title: { type: string, required: true }
      cover: { type: file }
repositories:
  documents: { entity: document, files: media }
services:
  documents: { repository: documents }
""" + _ROUTES


def _generate(tmp_path, spec):
    source = tmp_path / "docs.yaml"
    source.write_text(spec)
    compile_project(yaml_file=str(source), output_dir=str(tmp_path), target="fastapi")
    return tmp_path / "backend"


@pytest.fixture
def backend(tmp_path):
    return _generate(tmp_path, _FILESYSTEM_SPEC)


def test_emits_file_runtime_for_used_stores_only(backend):
    dependencies = backend / "dependencies"

    assert {"files.py", "multipart.py", "filesystem_store.py", "file_stores.py", "file_requests.py"} <= {
        path.name for path in dependencies.iterdir()
    }
    assert not (dependencies / "s3_store.py").exists()
    requirements = (backend / "requirements.txt").read_text().split()
    assert {"python-multipart", "puremagic", "anyio"} <= set(requirements)
    assert "aiobotocore" not in requirements
    assert "FILES_UPLOADS_PATH: str = './data/uploads'" in (backend / "settings.py").read_text()
    assert compileall.compile_dir(str(backend), quiet=1)


def test_payload_models_exclude_file_fields(backend):
    models = (backend / "models" / "documents.py").read_text()

    assert "title" in models
    assert "cover" not in models and "attachments" not in models


def test_entities_without_files_keep_json_bodies(backend):
    routes = (backend / "routes" / "tags.py").read_text()

    assert "payload: TagsCreatePayload" in routes
    assert "file_requests" not in routes and "record_files" not in routes


def test_s3_store_settings_keep_credentials_out_of_settings(tmp_path):
    backend = _generate(tmp_path, _S3_SPEC)
    settings = (backend / "settings.py").read_text()

    assert "FILES_MEDIA_ACCESS_KEY: SecretStr\n" in settings
    assert "FILES_MEDIA_SECRET_KEY: SecretStr\n" in settings
    assert "spec-secret" not in settings
    assert "FILES_MEDIA_CREATE_BUCKET: bool = True" in settings
    assert "FILES_MEDIA_ENDPOINT: str = 'http://localhost:9000'" in settings
    assert "spec-secret" in (backend / ".env").read_text()
    assert (backend / "dependencies" / "s3_store.py").exists()
    assert not (backend / "dependencies" / "filesystem_store.py").exists()
    assert "aiobotocore" in (backend / "requirements.txt").read_text().split()
    assert compileall.compile_dir(str(backend), quiet=1)


_APP_SCRIPT = """
import json
from pathlib import Path

from fastapi.testclient import TestClient

import app as appmod

PNG = b"\\x89PNG\\r\\n\\x1a\\n" + b"\\x00" * 64
PDF = b"%PDF-1.4\\n" + b"1 0 obj << >> endobj\\n" * 4
ROOT = Path(__import__("os").environ["FILES_UPLOADS_PATH"])


def stored():
    return sorted(p.name for p in (ROOT / "documents").glob("*")) if (ROOT / "documents").exists() else []


def data(value):
    return ("_data", (None, json.dumps(value), "application/json"))


with TestClient(appmod.app) as c:
    base = "/api/v1/documents"

    r = c.post(base, files=[data({"title": "a"}), ("cover", ("c.png", PNG, "image/png")),
                            ("attachments", ("one.pdf", PDF, "application/pdf")),
                            ("attachments", ("two.pdf", PDF, "application/pdf"))])
    assert r.status_code == 200, r.text
    doc = r.json()
    did = doc["id"]
    assert doc["title"] == "a"
    assert set(doc["cover"]) == {"id", "name", "size", "contentType", "sha256", "store", "uploadedAt"}
    assert doc["cover"]["contentType"] == "image/png" and doc["cover"]["size"] == len(PNG)
    assert [a["name"] for a in doc["attachments"]] == ["one.pdf", "two.pdf"]
    assert len(stored()) == 3

    assert c.get(f"{base}/{did}").json()["cover"] == doc["cover"]

    r = c.get(f"{base}/{did}/files/cover")
    assert r.status_code == 200 and r.content == PNG
    assert r.headers["content-type"] == "image/png"
    assert r.headers["content-disposition"].startswith("inline")
    assert r.headers["etag"] == '"' + doc["cover"]["sha256"] + '"'
    first = doc["attachments"][0]["id"]
    r = c.get(f"{base}/{did}/files/attachments/{first}")
    assert r.content == PDF and r.headers["content-disposition"].startswith("attachment")
    assert c.get(f"{base}/{did}/files/attachments/missing").status_code == 404

    assert c.post(base, json={"title": "b"}).status_code == 422
    assert c.post(base, json={"title": "b", "cover": {}}).status_code == 422
    assert c.post(base, files=[data({"title": "b"}), ("cover", ("big.png", PNG * 32, "image/png"))]).status_code == 413
    assert c.post(base, files=[data({"title": "b"}), ("cover", ("c.pdf", PDF, "application/pdf"))]).status_code == 415
    assert c.post(base, files=[data({}), ("cover", ("c.png", PNG, "image/png"))]).status_code == 422
    assert c.post(base, files=[("_data", (None, "{", "application/json")), ("cover", ("c.png", PNG, "image/png"))]).status_code == 400
    assert c.post(base, files=[data({"title": "b"}), ("cover", ("c.png", PNG, "image/png")),
                               ("attachments", ("1.pdf", PDF, "application/pdf")),
                               ("attachments", ("2.pdf", PDF, "application/pdf")),
                               ("attachments", ("3.pdf", PDF, "application/pdf"))]).status_code == 422
    assert len(stored()) == 3

    r = c.patch(f"{base}/{did}", json={"title": "renamed"})
    assert r.status_code == 200 and r.json()["cover"] == doc["cover"]
    assert c.patch(f"{base}/{did}", json={"cover": None}).status_code == 422

    r = c.patch(f"{base}/{did}", files=[data({"title": "patched"}), ("cover", ("new.png", PNG + b"\\x01", "image/png"))])
    assert r.status_code == 200, r.text
    patched = r.json()
    assert patched["title"] == "patched" and patched["cover"]["id"] != doc["cover"]["id"]
    assert patched["attachments"] == doc["attachments"]
    assert doc["cover"]["id"] not in stored() and len(stored()) == 3

    r = c.put(f"{base}/{did}", json={"title": "replaced"})
    assert r.status_code == 200 and r.json()["cover"] == patched["cover"]
    assert c.put(f"{base}/{did}", json={"title": "x", "cover": None}).status_code == 422

    r = c.put(f"{base}/{did}/files/cover", files=[("cover", ("again.png", PNG + b"\\x02", "image/png"))])
    assert r.status_code == 200, r.text
    cover = r.json()["cover"]
    assert cover["name"] == "again.png" and patched["cover"]["id"] not in stored()
    assert c.put(f"{base}/{did}/files/cover", files=[("cover", ("x.pdf", PDF, "application/pdf"))]).status_code == 415
    assert c.delete(f"{base}/{did}/files/cover").status_code == 422

    second = patched["attachments"][1]["id"]
    r = c.put(f"{base}/{did}/files/attachments/{second}", files=[("attachments", ("swap.pdf", PDF + b"%", "application/pdf"))])
    assert r.status_code == 200, r.text
    attachments = r.json()["attachments"]
    assert [a["name"] for a in attachments] == ["one.pdf", "swap.pdf"] and second not in stored()

    r = c.delete(f"{base}/{did}/files/attachments/{first}")
    assert r.status_code == 200 and [a["name"] for a in r.json()["attachments"]] == ["swap.pdf"]
    assert first not in stored() and len(stored()) == 2

    other = c.post(base, files=[data({"title": "other"}), ("cover", ("o.png", PNG, "image/png"))]).json()
    assert other["attachments"] == [] and len(stored()) == 3
    assert c.delete(f"{base}/{did}").status_code == 200
    assert stored() == [other["cover"]["id"]]
    assert c.get(f"{base}/{did}/files/cover").status_code == 404

    schema = c.get("/openapi.json").json()["paths"]
    create_body = schema[base]["post"]["requestBody"]["content"]
    assert set(create_body) == {"multipart/form-data", "application/json"}
    assert create_body["multipart/form-data"]["schema"]["required"] == ["cover"]
    assert "multipart/form-data" in schema[base + "/{id}/files/cover"]["put"]["requestBody"]["content"]
    assert "application/json" in schema[base + "/{id}"]["put"]["requestBody"]["content"]
    assert "404" in schema[base + "/{id}/files/cover"]["get"]["responses"]
print("FILES_OK")
"""


def test_generated_app_serves_uploaded_files(backend, tmp_path):
    env = {
        **os.environ,
        "DATABASE_URL": f"sqlite+aiosqlite:///{tmp_path / 'app.db'}",
        "FILES_UPLOADS_PATH": str(tmp_path / "uploads"),
    }
    result = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(_APP_SCRIPT)],
        cwd=str(backend),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert "FILES_OK" in result.stdout, result.stderr


_GUARDED_SPEC = """
version: "0.3"
api: { basePath: /api, version: v1 }
datastores:
  store: { type: postgres, dsn: "postgresql+asyncpg://localhost/docs", default: true }
  uploads: { type: filesystem, path: ./data/uploads }
entities:
  user:
    type: auth
    auth: { identifier: email, via: password }
    fields:
      id: { type: id }
      email: { type: string, required: true, unique: true }
  document:
    fields:
      id: { type: id }
      ownerId: { type: string, required: true }
      cover: { type: file }
repositories:
  users: { entity: user }
  documents: { entity: document, files: uploads }
services:
  documents: { repository: documents }
controllers:
  documents:
    base_path: /documents
    routes:
      create: { service: documents, method: POST, path: "", access: public }
      get:
        service: documents
        method: GET
        path: /{id}
        access:
          - given: { principal: "identity:user", document: documents }
            when: principal.sub not equals document.ownerId
            then: deny
          - then: allow
"""

_GUARDED_SCRIPT = """
import json

from fastapi.testclient import TestClient

import app as appmod
from dependencies.auth import get_optional_principal

caller = {}
appmod.app.dependency_overrides[get_optional_principal] = lambda: caller or None

with TestClient(appmod.app) as c:
    r = c.post("/api/v1/documents", files=[("_data", (None, json.dumps({"ownerId": "u1"}), "application/json")),
                                           ("cover", ("n.txt", b"hello", "text/plain"))])
    assert r.status_code == 200, r.text
    url = f"/api/v1/documents/{r.json()['id']}/files/cover"
    assert c.get(url).status_code == 401
    caller.update({"sub": "u2", "identity_collection": "users"})
    assert c.get(url).status_code == 403
    caller.update({"sub": "u1"})
    r = c.get(url)
    assert r.status_code == 200 and r.content == b"hello"
    assert r.headers["content-type"].startswith("text/plain")
print("GUARDED_OK")
"""


def test_file_routes_enforce_source_route_access(tmp_path):
    backend = _generate(tmp_path, _GUARDED_SPEC)
    env = {
        **os.environ,
        "DATABASE_URL": f"sqlite+aiosqlite:///{tmp_path / 'app.db'}",
        "FILES_UPLOADS_PATH": str(tmp_path / "uploads"),
    }
    result = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(_GUARDED_SCRIPT)],
        cwd=str(backend),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert "GUARDED_OK" in result.stdout, result.stderr
