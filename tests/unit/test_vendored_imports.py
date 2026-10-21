"""v0.3 vendored custom-handler packages.

Under v0.3 an ``imports`` entry vendors a package into the generated backend:
the source directory is copied whole into ``backend/<package>``, emitted code
imports the vendored package, its ``requires`` land in the manifest, and the
development server binds the same package name to the declared source so
``stackform run`` has the import graph the generated target has.
"""

import json
import subprocess
import sys
import textwrap

import pytest

from yaml_api_generator.cli.compiler import compile_project
from yaml_api_generator.parsers.yaml_parser import ConfigErrors, load_and_generate_ir

_PACKAGE_BODY = """
    from .helper import build


    async def publish(**kwargs):
        return build(kwargs)


    async def route(request):
        return build({"via": "route"})


    async def serve(ctx):
        ctx.response = build({"via": "serve"})
        return ctx
"""

_HELPER_BODY = """
    def build(data):
        return {"built": data}
"""

_MONGO_STORE = 'store: { type: mongodb, uri: "mongodb://localhost:27017", database: testdb, default: true }'
_SQL_STORE = 'store: { type: postgres, dsn: "postgresql+asyncpg://localhost/unused", default: true }'

_SPEC = """
version: "0.3"
api: {{ basePath: "" }}
imports:
  vend: {{ path: ./src/vend_pkg, package: vend_pkg, requires: ["httpx>=0.27"] }}
datastores:
  {store}
entities:
  post:
    fields:
      id: {{ type: id, format: uuidv4 }}
      title: {{ type: string, required: true }}
repositories:
  posts:
    entity: post
    operations:
      publish: {{ handler: vend.publish }}
services:
  posts: {{ repository: posts }}
  direct: {{ handler: vend.route }}
  served: {{ handler: vend.serve }}
controllers:
  posts:
    base_path: /posts
    routes:
      direct: {{ service: direct, method: POST, path: /direct, access: public }}
      served: {{ service: served, method: POST, path: /served, access: public }}
"""

_MINIMAL_SPEC = """
version: "0.3"
api: {{ basePath: "" }}
imports:
{imports}
datastores:
  {store}
entities:
  post:
    fields:
      id: {{ type: id, format: uuidv4 }}
      title: {{ type: string, required: true }}
repositories:
  posts: {{ entity: post }}
services:
  posts: {{ repository: posts }}
  direct: {{ handler: {handler} }}
controllers:
  posts:
    base_path: /posts
    routes:
      direct: {{ service: direct, method: POST, path: /direct, access: public }}
"""


def _write_package(root, package, body=_PACKAGE_BODY, helper=_HELPER_BODY):
    pkg = root / package
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text(textwrap.dedent(body))
    if helper is not None:
        (pkg / "helper.py").write_text(textwrap.dedent(helper))
    return pkg


def _write_spec(tmp_path, text):
    spec = tmp_path / "spec.yaml"
    spec.write_text(text)
    return spec


def _minimal(tmp_path, imports, handler="vend.route", store=_MONGO_STORE):
    return _write_spec(tmp_path, _MINIMAL_SPEC.format(
        imports=textwrap.indent(textwrap.dedent(imports).strip(), "  "),
        handler=handler,
        store=store,
    ))


def _compile(tmp_path, target="fastapi", store=_MONGO_STORE):
    _write_package(tmp_path / "src", "vend_pkg")
    spec = _write_spec(tmp_path, _SPEC.format(store=store))
    out = tmp_path / "out"
    compile_project(str(spec), output_dir=str(out), target=target)
    return out / "backend"


def _run(script):
    subprocess.run([sys.executable, "-c", textwrap.dedent(script)], check=True)


def _codes(spec):
    with pytest.raises(ConfigErrors) as exc:
        load_and_generate_ir(str(spec))
    return [error.code for error in exc.value.errors]


@pytest.mark.parametrize("target", ["fastapi", "drf", "raw"])
def test_vendored_package_is_a_working_package_inside_every_target(tmp_path, target):
    backend = _compile(tmp_path, target)

    vendored = backend / "vend_pkg"
    assert (vendored / "helper.py").is_file()
    assert not vendored.samefile(tmp_path / "src" / "vend_pkg")

    _run(f"""
        import asyncio, sys
        sys.path.insert(0, {str(backend)!r})
        import vend_pkg
        assert vend_pkg.__file__.startswith({str(backend)!r})
        assert asyncio.run(vend_pkg.publish(x=1)) == {{"built": {{"x": 1}}}}
    """)


@pytest.mark.parametrize(
    "target,module",
    [("fastapi", "repositories.posts"), ("drf", "api.repositories.posts"), ("raw", "repositories.posts")],
)
def test_generated_repository_operation_calls_the_vendored_handler(tmp_path, target, module):
    backend = _compile(tmp_path, target)

    _run(f"""
        import asyncio, sys
        sys.path.insert(0, {str(backend)!r})
        from {module} import PostsRepository
        result = asyncio.run(PostsRepository.publish(None, title="t"))
        assert result == {{"built": {{"title": "t"}}}}, result
    """)


def test_generated_fastapi_route_dispatches_to_the_vendored_handler(tmp_path):
    backend = _compile(tmp_path, "fastapi")

    _run(f"""
        import sys
        sys.path.insert(0, {str(backend)!r})
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from routes._handlers import router

        app = FastAPI()
        app.include_router(router)
        response = TestClient(app).post("/posts/direct", json={{}})
        assert response.status_code == 200, response.text
        assert response.json() == {{"built": {{"via": "route"}}}}
    """)


def test_dev_server_route_executes_the_vendored_handler(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from yaml_api_generator.server import build_app

    monkeypatch.setenv("YAML_API_DB_STORE_DSN", f"sqlite+aiosqlite:///{tmp_path / 'db.sqlite'}")
    _write_package(tmp_path / "src", "vend_pkg")
    spec = _write_spec(tmp_path, _SPEC.format(store=_SQL_STORE))

    response = TestClient(build_app(str(spec))).post("/posts/served", json={})
    assert response.status_code == 200, response.text
    assert response.json() == {"built": {"via": "serve"}}


@pytest.mark.asyncio
async def test_raw_dev_server_route_executes_the_vendored_handler(tmp_path, monkeypatch):
    from yaml_api_generator.server import build_raw_app

    monkeypatch.setenv("YAML_API_DB_STORE_DSN", f"sqlite+aiosqlite:///{tmp_path / 'db.sqlite'}")
    _write_package(tmp_path / "src", "vend_pkg")
    spec = _write_spec(tmp_path, _SPEC.format(store=_SQL_STORE))
    app = build_raw_app(str(spec))

    scope = {"type": "http", "method": "POST", "path": "/posts/served", "headers": []}
    messages = []

    async def receive():
        return {"type": "http.request", "body": b"{}", "more_body": False}

    async def send(message):
        messages.append(message)

    await app(scope, receive, send)
    start = next(m for m in messages if m["type"] == "http.response.start")
    body = next(m for m in messages if m["type"] == "http.response.body")
    assert start["status"] == 200
    assert json.loads(body["body"]) == {"built": {"via": "serve"}}


@pytest.mark.parametrize("target", ["fastapi", "drf", "raw"])
def test_requires_land_in_every_target_manifest_and_intersect(tmp_path, target):
    _write_package(tmp_path / "src", "vend_a", "async def a(**k):\n    return {}\n", helper=None)
    _write_package(tmp_path / "src", "vend_b", "async def b(**k):\n    return {}\n", helper=None)
    spec = _minimal(
        tmp_path,
        """
        va: { path: ./src/vend_a, package: vend_a, requires: ["httpx>=0.27", "httpx<1"] }
        vb: { path: ./src/vend_b, package: vend_b, requires: ["httpx>=0.26"] }
        """,
        handler="va.a",
    )
    out = tmp_path / "out"
    compile_project(str(spec), output_dir=str(out), target=target)

    requirements = (out / "backend" / "requirements.txt").read_text().splitlines()
    assert [line for line in requirements if line.startswith("httpx")] == ["httpx<1,>=0.26,>=0.27"]


def test_incompatible_pins_raise_conflict(tmp_path):
    _write_package(tmp_path / "src", "vend_a", "async def a(**k):\n    return {}\n", helper=None)
    _write_package(tmp_path / "src", "vend_b", "async def b(**k):\n    return {}\n", helper=None)
    spec = _minimal(
        tmp_path,
        """
        va: { path: ./src/vend_a, package: vend_a, requires: ["httpx==0.27"] }
        vb: { path: ./src/vend_b, package: vend_b, requires: ["httpx==0.28"] }
        """,
        handler="va.a",
    )
    assert _codes(spec) == ["IMPORT_REQUIRES_CONFLICT"]


def test_package_name_collision_raises(tmp_path):
    _write_package(tmp_path / "src", "one")
    _write_package(tmp_path / "src", "two")
    spec = _minimal(
        tmp_path,
        """
        one: { path: ./src/one, package: shared }
        two: { path: ./src/two, package: shared }
        """,
        handler="one.route",
    )
    assert _codes(spec) == ["IMPORT_PACKAGE_COLLISION"]


def test_handler_referencing_undeclared_package_raises(tmp_path):
    _write_package(tmp_path / "src", "vend_pkg")
    spec = _minimal(
        tmp_path,
        "vend: { path: ./src/vend_pkg, package: vend_pkg }",
        handler="missing.route",
    )
    assert _codes(spec) == ["IMPORT_UNDECLARED_PACKAGE"]


def test_v03_bare_string_import_rejected(tmp_path):
    spec = _minimal(tmp_path, "vend: some.author.module", handler="vend.route")
    assert _codes(spec) == ["SCHEMA_VALIDATION_ERROR"]


def test_source_escaping_the_spec_directory_is_rejected(tmp_path):
    _write_package(tmp_path.parent / "outside_pkg_root", "outside_pkg")
    spec = _minimal(
        tmp_path,
        "vend: { path: ../outside_pkg_root/outside_pkg, package: outside_pkg }",
        handler="vend.route",
    )
    assert _codes(spec) == ["IMPORT_SOURCE_OUTSIDE_SPEC"]


def test_absolute_source_is_rejected(tmp_path):
    outside = _write_package(tmp_path.parent / "absolute_pkg_root", "absolute_pkg")
    spec = _minimal(
        tmp_path,
        f"vend: {{ path: {outside}, package: absolute_pkg }}",
        handler="vend.route",
    )
    assert _codes(spec) == ["IMPORT_SOURCE_OUTSIDE_SPEC"]


def test_symlink_leaving_the_vendored_tree_is_rejected(tmp_path):
    outside = tmp_path / "outside.txt"
    outside.write_text("not part of the vendored tree")
    pkg = _write_package(tmp_path / "src", "vend_pkg")
    (pkg / "leak.txt").symlink_to(outside)
    spec = _minimal(
        tmp_path,
        "vend: { path: ./src/vend_pkg, package: vend_pkg }",
        handler="vend.route",
    )
    assert _codes(spec) == ["IMPORT_SOURCE_ESCAPING_SYMLINK"]


def test_symlink_staying_inside_the_tree_is_copied_as_a_link(tmp_path):
    pkg = _write_package(tmp_path / "src", "vend_pkg")
    (pkg / "alias.py").symlink_to(pkg / "helper.py")
    spec = _write_spec(tmp_path, _SPEC.format(store=_MONGO_STORE))
    out = tmp_path / "out"
    compile_project(str(spec), output_dir=str(out))

    copied = out / "backend" / "vend_pkg" / "alias.py"
    assert copied.is_symlink()
    assert copied.read_text() == (pkg / "helper.py").read_text()


def test_source_without_init_is_rejected(tmp_path):
    (tmp_path / "src" / "loose").mkdir(parents=True)
    (tmp_path / "src" / "loose" / "route.py").write_text("async def route(request):\n    return {}\n")
    spec = _minimal(
        tmp_path,
        "vend: { path: ./src/loose, package: loose }",
        handler="vend.route",
    )
    assert _codes(spec) == ["IMPORT_SOURCE_NOT_PACKAGE"]


def test_package_shadowing_a_generated_module_is_rejected(tmp_path):
    _write_package(tmp_path / "src", "repositories")
    spec = _minimal(
        tmp_path,
        "vend: { path: ./src/repositories, package: repositories }",
        handler="vend.route",
    )
    with pytest.raises(ConfigErrors) as exc:
        compile_project(str(spec), output_dir=str(tmp_path / "out"))
    assert [error.code for error in exc.value.errors] == ["IMPORT_PACKAGE_SHADOWS_TARGET"]


def test_package_name_must_be_an_identifier(tmp_path):
    _write_package(tmp_path / "src", "vend_pkg")
    spec = _minimal(
        tmp_path,
        "vend: { path: ./src/vend_pkg, package: ../escape }",
        handler="vend.route",
    )
    with pytest.raises(ConfigErrors):
        load_and_generate_ir(str(spec))


def test_rebuilding_into_one_output_directory_refreshes_the_vendored_copy(tmp_path):
    pkg = _write_package(tmp_path / "src", "vend_pkg")
    (pkg / "stale.py").write_text("STALE = True\n")
    spec = _write_spec(tmp_path, _SPEC.format(store=_MONGO_STORE))
    out = tmp_path / "out"
    compile_project(str(spec), output_dir=str(out))
    assert (out / "backend" / "vend_pkg" / "stale.py").is_file()

    (pkg / "stale.py").unlink()
    (pkg / "helper.py").write_text("def build(data):\n    return {'rebuilt': data}\n")
    compile_project(str(spec), output_dir=str(out))

    assert not (out / "backend" / "vend_pkg" / "stale.py").exists()
    assert "rebuilt" in (out / "backend" / "vend_pkg" / "helper.py").read_text()


_V02_SPEC = """
version: "0.2"
api: { basePath: "" }
imports:
  handlers: my_app.handlers
datastores:
  store: { type: mongodb, uri: "mongodb://localhost", database: x, default: true }
entities:
  post:
    fields:
      id: { type: id }
      title: { type: string, required: true }
repositories:
  posts:
    entity: post
    operations:
      publish: { handler: raw_module.publish }
services:
  posts:
    repository: posts
    operations:
      publish: { handler: handlers.publish }
controllers:
  posts:
    base_path: /posts
    routes:
      list: { service: list-posts, method: GET, path: "", access: public }
"""

_V03_NO_IMPORTS_SPEC = _V02_SPEC.replace('version: "0.2"', 'version: "0.3"').replace(
    "imports:\n  handlers: my_app.handlers\n", ""
).replace("publish: { handler: handlers.publish }", "publish: { handler: my_app.handlers.publish }")


def test_v02_bare_string_import_stays_valid_and_resolved(tmp_path):
    result = load_and_generate_ir(str(_write_spec(tmp_path, _V02_SPEC)))

    assert result.ir.vendored_imports == ()
    assert result.ir.vendored_requirements == ()
    assert result.ir.services["publish-posts"].handler == "my_app.handlers.publish"
    assert result.ir.repositories["posts"].operations["publish"].handler == "raw_module.publish"


def test_v02_output_is_not_vendored_and_stays_stable(tmp_path):
    spec = _write_spec(tmp_path, _V02_SPEC)
    out_a = tmp_path / "a"
    out_b = tmp_path / "b"
    compile_project(str(spec), output_dir=str(out_a))
    compile_project(str(spec), output_dir=str(out_b))

    repository = (out_a / "backend" / "repositories" / "posts.py").read_text()
    assert "import raw_module" in repository
    assert "await raw_module.publish(**kwargs)" in repository

    assert not (out_a / "backend" / "my_app").exists()
    requirements_a = (out_a / "backend" / "requirements.txt").read_text()
    assert requirements_a == (out_b / "backend" / "requirements.txt").read_text()
    assert "my_app" not in requirements_a


def test_v03_without_imports_keeps_verbatim_handlers(tmp_path):
    result = load_and_generate_ir(str(_write_spec(tmp_path, _V03_NO_IMPORTS_SPEC)))

    assert result.ir.vendored_imports == ()
    assert result.ir.services["publish-posts"].handler == "my_app.handlers.publish"
    assert result.ir.repositories["posts"].operations["publish"].handler == "raw_module.publish"
