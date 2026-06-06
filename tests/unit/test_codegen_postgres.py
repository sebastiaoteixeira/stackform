"""Codegen for a PostgreSQL-backed FastAPI app.

Generates an all-Postgres backend, checks the emitted artifacts, then runs the
generated app against SQLite (DATABASE_URL override) in a subprocess to confirm
it boots and serves CRUD without a Postgres server.
"""

import compileall
import os
import subprocess
import sys
import textwrap

import pytest

from yaml_api_generator.cli.compiler import compile_project


_SPEC = """
version: "0.2"
api: { basePath: /api, version: v1 }
datastores:
  store: { type: postgres, dsn: "postgresql+asyncpg://localhost/blog", default: true }
entities:
  post:
    fields:
      id: { type: id }
      title: { type: string, required: true, maxLength: 200 }
      views: { type: number }
      published: { type: boolean }
repositories:
  posts: { entity: post }
services:
  posts: { repository: posts }
controllers:
  posts:
    base_path: /posts
    routes:
      create: { service: posts, method: POST, path: "", access: public }
      list:   { service: posts, method: GET, path: "", access: public }
      get:    { service: posts, method: GET, path: "/{id}", access: public }
      update: { service: posts, method: PATCH, path: "/{id}", access: public }
      delete: { service: posts, method: DELETE, path: "/{id}", access: public }
"""


def _generate(tmp_path):
    spec = tmp_path / "blog.yaml"
    spec.write_text(_SPEC)
    compile_project(yaml_file=str(spec), output_dir=str(tmp_path), target="fastapi")
    return tmp_path / "backend"


def test_emits_sql_artifacts(tmp_path):
    backend = _generate(tmp_path)

    assert (backend / "dependencies" / "postgres.py").exists()
    assert (backend / "repositories" / "_sql_ops.py").exists()
    assert not (backend / "dependencies" / "mongodb.py").exists()

    repo = (backend / "repositories" / "posts.py").read_text()
    assert "sa.Table(" in repo and "SQLRepositoryBase" in repo

    requirements = (backend / "requirements.txt").read_text()
    assert "sqlalchemy[asyncio]" in requirements and "asyncpg" in requirements
    assert "pymongo" not in requirements

    assert compileall.compile_dir(str(backend), quiet=1)


def test_generated_app_runs_on_sqlite(tmp_path):
    backend = _generate(tmp_path)

    script = textwrap.dedent("""
        from fastapi.testclient import TestClient
        import app as appmod
        with TestClient(appmod.app) as c:
            r = c.post("/api/v1/posts", json={"title": "x", "views": 1, "published": True})
            assert r.status_code == 200, r.text
            pid = r.json()["id"]
            assert len(c.get("/api/v1/posts").json()) == 1
            assert c.get(f"/api/v1/posts/{pid}").json()["id"] == pid
            assert c.patch(f"/api/v1/posts/{pid}", json={"title": "y"}).json()["title"] == "y"
            assert c.delete(f"/api/v1/posts/{pid}").status_code == 200
            assert c.get("/api/v1/posts").json() == []
        print("CRUD_OK")
    """)
    env = {**os.environ, "DATABASE_URL": f"sqlite+aiosqlite:///{tmp_path / 'app.db'}"}
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=str(backend),
        env=env,
        capture_output=True,
        text=True,
    )
    assert "CRUD_OK" in result.stdout, result.stderr
