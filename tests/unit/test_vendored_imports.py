"""v0.3 vendored custom-handler packages.

Under v0.3 an ``imports`` entry vendors a package into the generated backend:
its source directory is copied whole into ``backend/<package>``, emitted code
imports the vendored package, and its ``requires`` land in the manifest. The
v0.2 bare dotted-string form stays untouched.
"""

import importlib
import sys
import textwrap

import pytest

from yaml_api_generator.cli.compiler import compile_project
from yaml_api_generator.parsers.yaml_parser import ConfigErrors, load_and_generate_ir


def _write_package(root, package, body, helper=None):
    pkg = root / package
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text(textwrap.dedent(body))
    if helper is not None:
        (pkg / "helper.py").write_text(textwrap.dedent(helper))


def _spec(imports, services="", controllers=""):
    return textwrap.dedent(
        f"""
        version: "0.3"
        api: {{ basePath: "" }}
        imports:
        {textwrap.indent(textwrap.dedent(imports), "          ")}
        datastores:
          store: {{ type: mongodb, uri: "mongodb://localhost", database: x, default: true }}
        entities:
          post:
            fields:
              id: {{ type: id }}
              title: {{ type: string, required: true }}
        repositories:
          posts: {{ entity: post }}
        services:
          posts:
            repository: posts
            operations:
        {textwrap.indent(textwrap.dedent(services), "              ")}
        controllers:
          posts:
            base_path: /posts
            routes:
        {textwrap.indent(textwrap.dedent(controllers), "              ")}
        """
    )


def _compile(tmp_path, spec_text):
    spec = tmp_path / "spec.yaml"
    spec.write_text(spec_text)
    out = tmp_path / "out"
    compile_project(str(spec), output_dir=str(out))
    return out / "backend"


def test_vendored_package_copied_and_importable(tmp_path):
    _write_package(
        tmp_path / "src",
        "vend_alpha",
        """
        async def publish(**kwargs):
            return {"ok": True, "kwargs": kwargs}
        """,
    )
    spec = _spec(
        imports="vend: { path: ./src/vend_alpha, package: vend_alpha }",
        services="publish: { handler: vend.publish }",
        controllers="publish: { service: publish-posts, method: POST, path: /publish, access: public }",
    )
    backend = _compile(tmp_path, spec)

    vendored = backend / "vend_alpha"
    assert (vendored / "__init__.py").exists()
    assert not (tmp_path / "src" / "vend_alpha").samefile(vendored)

    sys.path.insert(0, str(backend))
    try:
        module = importlib.import_module("vend_alpha")
        importlib.reload(module)
        assert module is not None
    finally:
        sys.path.remove(str(backend))
        sys.modules.pop("vend_alpha", None)


_REPO_HANDLER_SPEC = """
version: "0.3"
api: { basePath: "" }
imports:
  vend: { path: ./src/vend_beta, package: vend_beta }
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
      publish: { handler: vend.publish }
controllers:
  posts:
    base_path: /posts
    routes:
      publish: { service: publish, method: POST, path: /publish, access: public }
services:
  publish: { repository: posts, operation: publish }
"""


def test_emitted_code_imports_vendored_package(tmp_path):
    _write_package(
        tmp_path / "src",
        "vend_beta",
        "async def publish(**kwargs):\n    return {}\n",
    )
    spec = tmp_path / "spec.yaml"
    spec.write_text(_REPO_HANDLER_SPEC)
    out = tmp_path / "out"
    compile_project(str(spec), output_dir=str(out))
    repository = (out / "backend" / "repositories" / "posts.py").read_text()
    assert "import vend_beta" in repository
    assert "await vend_beta.publish(**kwargs)" in repository
    assert "vend.publish" not in repository


def test_whole_directory_copied_with_local_helper(tmp_path):
    _write_package(
        tmp_path / "src",
        "vend_gamma",
        """
        from .helper import build

        async def publish(**kwargs):
            return build(kwargs)
        """,
        helper="""
        def build(data):
            return {"built": data}
        """,
    )
    spec = _spec(
        imports="vend: { path: ./src/vend_gamma, package: vend_gamma }",
        services="publish: { handler: vend.publish }",
        controllers="publish: { service: publish-posts, method: POST, path: /publish, access: public }",
    )
    backend = _compile(tmp_path, spec)

    assert (backend / "vend_gamma" / "helper.py").exists()

    sys.path.insert(0, str(backend))
    try:
        module = importlib.import_module("vend_gamma")
        importlib.reload(module)
        import asyncio

        result = asyncio.run(module.publish(x=1))
        assert result == {"built": {"x": 1}}
    finally:
        sys.path.remove(str(backend))
        for name in ("vend_gamma", "vend_gamma.helper"):
            sys.modules.pop(name, None)


def test_requires_land_in_manifest_and_intersect(tmp_path):
    _write_package(tmp_path / "src", "vend_a", "async def a(**k):\n    return {}\n")
    _write_package(tmp_path / "src", "vend_b", "async def b(**k):\n    return {}\n")
    spec = _spec(
        imports="""
        va: { path: ./src/vend_a, package: vend_a, requires: ["httpx>=0.27"] }
        vb: { path: ./src/vend_b, package: vend_b, requires: ["httpx>=0.26"] }
        """,
        services="""
        a: { handler: va.a }
        b: { handler: vb.b }
        """,
        controllers="""
        a: { service: a-posts, method: POST, path: /a, access: public }
        b: { service: b-posts, method: POST, path: /b, access: public }
        """,
    )
    backend = _compile(tmp_path, spec)
    requirements = (backend / "requirements.txt").read_text().splitlines()
    httpx_lines = [line for line in requirements if line.startswith("httpx")]
    assert httpx_lines == ["httpx>=0.26,>=0.27"]


def test_two_packages_both_vendored_and_callable(tmp_path):
    _write_package(tmp_path / "src", "vend_one", "async def run(**k):\n    return 1\n")
    _write_package(tmp_path / "src", "vend_two", "async def run(**k):\n    return 2\n")
    spec = _spec(
        imports="""
        one: { path: ./src/vend_one, package: vend_one }
        two: { path: ./src/vend_two, package: vend_two }
        """,
        services="""
        one: { handler: one.run }
        two: { handler: two.run }
        """,
        controllers="""
        one: { service: one-posts, method: POST, path: /one, access: public }
        two: { service: two-posts, method: POST, path: /two, access: public }
        """,
    )
    backend = _compile(tmp_path, spec)
    assert (backend / "vend_one" / "__init__.py").exists()
    assert (backend / "vend_two" / "__init__.py").exists()

    sys.path.insert(0, str(backend))
    try:
        import asyncio

        m1 = importlib.import_module("vend_one")
        m2 = importlib.import_module("vend_two")
        importlib.reload(m1)
        importlib.reload(m2)
        assert asyncio.run(m1.run()) == 1
        assert asyncio.run(m2.run()) == 2
    finally:
        sys.path.remove(str(backend))
        sys.modules.pop("vend_one", None)
        sys.modules.pop("vend_two", None)


def _errors(tmp_path, spec_text):
    spec = tmp_path / "spec.yaml"
    spec.write_text(spec_text)
    with pytest.raises(ConfigErrors) as exc:
        load_and_generate_ir(str(spec))
    return [e.code for e in exc.value.errors]


def test_incompatible_pins_raise_conflict(tmp_path):
    spec = _spec(
        imports="""
        va: { path: ./src/vend_a, package: vend_a, requires: ["httpx==0.27"] }
        vb: { path: ./src/vend_b, package: vend_b, requires: ["httpx==0.28"] }
        """,
        services="""
        a: { handler: va.a }
        b: { handler: vb.b }
        """,
        controllers="""
        a: { service: a-posts, method: POST, path: /a, access: public }
        b: { service: b-posts, method: POST, path: /b, access: public }
        """,
    )
    assert "IMPORT_REQUIRES_CONFLICT" in _errors(tmp_path, spec)


def test_package_name_collision_raises(tmp_path):
    spec = _spec(
        imports="""
        a: { path: ./src/one, package: shared }
        vend: { path: ./src/two, package: shared }
        """,
        services="publish: { handler: vend.publish }",
        controllers="publish: { service: publish-posts, method: POST, path: /publish, access: public }",
    )
    assert "IMPORT_PACKAGE_COLLISION" in _errors(tmp_path, spec)


def test_handler_referencing_undeclared_package_raises(tmp_path):
    spec = _spec(
        imports="declared: { path: ./src/declared, package: declared }",
        services="publish: { handler: missing.publish }",
        controllers="publish: { service: publish-posts, method: POST, path: /publish, access: public }",
    )
    assert "IMPORT_UNDECLARED_PACKAGE" in _errors(tmp_path, spec)


def test_v03_bare_string_import_rejected(tmp_path):
    spec = _spec(
        imports="handlers: some.author.module",
        services="publish: { handler: handlers.publish }",
        controllers="publish: { service: publish-posts, method: POST, path: /publish, access: public }",
    )
    assert "IMPORT_BARE_STRING" in _errors(tmp_path, spec)


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


def test_v02_bare_string_import_stays_valid_and_resolved(tmp_path):
    spec = tmp_path / "spec.yaml"
    spec.write_text(_V02_SPEC)
    result = load_and_generate_ir(str(spec))

    assert result.ir.vendored_imports == ()
    assert result.ir.vendored_requirements == ()
    assert result.ir.services["publish-posts"].handler == "my_app.handlers.publish"
    assert result.ir.repositories["posts"].operations["publish"].handler == "raw_module.publish"


def test_v02_output_byte_identical_and_not_vendored(tmp_path):
    spec = tmp_path / "spec.yaml"
    spec.write_text(_V02_SPEC)
    out_a = tmp_path / "a"
    out_b = tmp_path / "b"
    compile_project(str(spec), output_dir=str(out_a))
    compile_project(str(spec), output_dir=str(out_b))

    repository = (out_a / "backend" / "repositories" / "posts.py").read_text()
    assert "import raw_module" in repository
    assert "await raw_module.publish(**kwargs)" in repository

    assert not (out_a / "backend" / "my_app").exists()
    requirements_a = (out_a / "backend" / "requirements.txt").read_text()
    requirements_b = (out_b / "backend" / "requirements.txt").read_text()
    assert requirements_a == requirements_b
    assert "my_app" not in requirements_a
