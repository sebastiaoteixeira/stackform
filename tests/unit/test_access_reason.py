import compileall
import subprocess
import sys
import textwrap

import pytest

from yaml_api_generator.generators.backend.context_builder import build_context
from yaml_api_generator.generators.backend.drf.generator import DRFGenerator
from yaml_api_generator.generators.backend.fastapi.generator import FastAPIGenerator
from yaml_api_generator.generators.backend.raw.generator import RawASGIGenerator
from yaml_api_generator.ir import IRDocumentBinding
from yaml_api_generator.ir.when import FieldRef, NotEquals
from yaml_api_generator.parsers.yaml_parser import ConfigErrors, load_and_generate_ir
from yaml_api_generator.server.common.context_builder import build_runtime_context
from yaml_api_generator.server.common.request_context import RequestContext
from yaml_api_generator.server.common.server_context import RuntimeAccessRule
from yaml_api_generator.server.common.steps.authorization import (
    ForbiddenError,
    PostFetchAuthorizeStep,
)


_SPEC = """
version: "{version}"
api:
  name: access-reason
  basePath: /api
mongo:
  uri: mongodb://localhost:27017
  database: testdb
entities:
  user:
    type: auth
    auth:
      identifier: email
      via: password
    fields:
      id: {{ type: id }}
      email: {{ type: string, required: true, unique: true }}
  post:
    fields:
      id: {{ type: id }}
      title: {{ type: string, required: true }}
      ownerId: {{ type: string, required: true }}
repositories:
  users:
    entity: user
  posts:
    entity: post
services:
  posts:
    repository: posts
  notify:
    handler: app.handlers.notify
controllers:
  posts:
    base_path: /posts
    routes:
      create:
        service: posts
        method: POST
        path: /
        access:
          - given:
              principal: identity:user
            when: principal.sub equals 'blocked'
            then: deny
            reason: Blocked accounts cannot create posts.
          - then: allow
      get:
        service: posts
        method: GET
        path: /{{id}}
        access:
          - given:
              principal: identity:user
              document: posts
            when: principal.sub not equals document.ownerId
            then: deny
            reason: Only the owner may read this post.
          - then: allow
      notify:
        service: notify
        method: POST
        path: /notify
        access:
          - given:
              principal: identity:user
            then: deny
            reason: Notifications are disabled for this caller.
"""


def _load(tmp_path, version="0.3"):
    path = tmp_path / f"access-reason-{version}.yaml"
    path.write_text(textwrap.dedent(_SPEC.format(version=version)))
    try:
        return load_and_generate_ir(str(path)).ir
    except ConfigErrors as exc:
        pytest.fail("\n".join(f"{error.code}: {error.message}" for error in exc.errors))


def test_reason_is_enabled_only_for_v03_contexts(tmp_path):
    v03 = _load(tmp_path, "0.3")
    v02 = _load(tmp_path, "0.2")

    assert build_runtime_context(v03).routes[0].access_rules[0].reason == (
        "Blocked accounts cannot create posts."
    )
    assert build_context(v03).routes[0].access_rules[0].reason == (
        "Blocked accounts cannot create posts."
    )
    assert build_runtime_context(v02).routes[0].access_rules[0].reason is None
    assert build_context(v02).routes[0].access_rules[0].reason is None


def test_post_fetch_deny_surfaces_only_the_matching_rule_reason():
    rule = RuntimeAccessRule(
        principal="identity:users",
        document_symbols={"document": IRDocumentBinding("posts")},
        when=NotEquals(
            FieldRef("principal", ("sub",)),
            FieldRef("document", ("ownerId",)),
        ),
        effect="deny",
        reason="Only the owner may read this post.",
    )
    ctx = RequestContext(
        method="GET",
        path="/posts/p1",
        api_version=None,
        collection="posts",
        operation="get",
        headers={},
        url_params={"id": "p1"},
        repository=None,
        principal={"sub": "u1", "identity_collection": "users"},
        body=None,
        response={"id": "p1", "ownerId": "u2"},
    )

    with pytest.raises(ForbiddenError, match="^Only the owner may read this post[.]$"):
        PostFetchAuthorizeStep([rule])(ctx)


@pytest.mark.parametrize(
    "generator",
    [FastAPIGenerator(), DRFGenerator(), RawASGIGenerator()],
)
def test_generated_backends_compile_with_reasoned_denials(generator, tmp_path):
    output = tmp_path / generator.__class__.__name__
    generator.generate(build_context(_load(tmp_path)), output)

    assert compileall.compile_dir(str(output), quiet=1)
    route_path = {
        FastAPIGenerator: output / "routes" / "posts.py",
        DRFGenerator: output / "api" / "views" / "posts.py",
        RawASGIGenerator: output / "routes" / "posts.py",
    }[generator.__class__]
    handler_path = {
        FastAPIGenerator: output / "routes" / "_handlers.py",
        DRFGenerator: output / "api" / "views" / "_handlers.py",
        RawASGIGenerator: output / "routes" / "handlers.py",
    }[generator.__class__]
    route_source = route_path.read_text()
    handler_source = handler_path.read_text()
    assert "Blocked accounts cannot create posts." in route_source
    assert "Only the owner may read this post." in route_source
    assert "Notifications are disabled for this caller." in handler_source


def test_generated_fastapi_surfaces_prefetch_and_postfetch_reasons(tmp_path):
    output = tmp_path / "fastapi"
    FastAPIGenerator().generate(build_context(_load(tmp_path)), output)
    script = textwrap.dedent(
        f"""
        import os
        import sys

        os.environ["JWT_SECRET"] = "test-secret-at-least-thirty-two-bytes"
        sys.path.insert(0, {str(output)!r})

        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from dependencies.auth import require_principal
        from dependencies.services import get_posts_service
        from routes._handlers import router as handlers_router
        from routes.posts import router

        class Service:
            async def create(self, data):
                return {{"id": "p1", **data}}

            async def get(self, record_id):
                return {{"id": record_id, "title": "Post", "ownerId": "u2"}}

        current = {{
            "sub": "blocked",
            "identity_collection": "users",
            "roles": [],
            "record": {{"id": "blocked"}},
        }}

        async def principal():
            return current

        app = FastAPI()
        app.include_router(router)
        app.include_router(handlers_router)
        app.dependency_overrides[require_principal] = principal
        app.dependency_overrides[get_posts_service] = Service
        client = TestClient(app)

        response = client.post(
            "/posts/",
            json={{"title": "Post", "ownerId": "blocked"}},
        )
        assert response.status_code == 403, response.text
        assert response.json() == {{
            "detail": "Blocked accounts cannot create posts."
        }}

        response = client.post("/posts/notify")
        assert response.status_code == 403, response.text
        assert response.json() == {{
            "detail": "Notifications are disabled for this caller."
        }}

        current["sub"] = "u1"
        response = client.post(
            "/posts/",
            json={{"title": "Post", "ownerId": "u1"}},
        )
        assert response.status_code == 200, response.text
        assert "Blocked accounts" not in response.text

        response = client.get("/posts/p1")
        assert response.status_code == 403, response.text
        assert response.json() == {{
            "detail": "Only the owner may read this post."
        }}

        current["sub"] = "u2"
        response = client.get("/posts/p1")
        assert response.status_code == 200, response.text
        assert response.json()["ownerId"] == "u2"
        """
    )

    subprocess.run([sys.executable, "-c", script], check=True)


def test_generated_raw_asgi_surfaces_prefetch_and_postfetch_reasons(tmp_path):
    output = tmp_path / "raw"
    RawASGIGenerator().generate(build_context(_load(tmp_path)), output)
    script = textwrap.dedent(
        f"""
        import asyncio
        import os
        import sys

        os.environ["JWT_SECRET"] = "test-secret-at-least-thirty-two-bytes"
        sys.path.insert(0, {str(output)!r})

        from routes import posts

        class Collection:
            async def find_one(self, criteria):
                return {{"id": criteria["id"], "title": "Post", "ownerId": "u2"}}

        class Database:
            def __getitem__(self, name):
                assert name == "posts"
                return Collection()

        current = {{"sub": "blocked", "identity_collection": "users", "roles": []}}

        async def principal(headers, db):
            return current

        posts.resolve_principal = principal
        database = Database()

        result = asyncio.run(posts.handle_create_posts(
            {{}},
            {{"title": "Post", "ownerId": "blocked"}},
            {{}},
            database,
        ))
        assert result == (403, {{"detail": "Blocked accounts cannot create posts."}})

        current["sub"] = "u1"
        result = asyncio.run(posts.handle_get_posts(
            {{"id": "p1"}}, None, {{}}, database
        ))
        assert result == (403, {{"detail": "Only the owner may read this post."}})

        current["sub"] = "u2"
        status, document = asyncio.run(posts.handle_get_posts(
            {{"id": "p1"}}, None, {{}}, database
        ))
        assert status == 200
        assert document["ownerId"] == "u2"
        """
    )

    subprocess.run([sys.executable, "-c", script], check=True)
