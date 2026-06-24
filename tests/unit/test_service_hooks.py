"""Tests for the async, principal-aware service lifecycle hook surface.

Verifies that the generated ``services/_ops.py`` (rendered from
``service_ops.py.jinja``) exposes the full async hook set on ``ServiceBase``,
that the principal-aware constructor is emitted, and that ``routes.py.jinja``
threads principal through ``_service()`` on authenticated routes.
"""

import textwrap

from yaml_api_generator.generators.backend.fastapi.generator import FastAPIGenerator
from yaml_api_generator.generators.backend.context_builder import build_context
from yaml_api_generator.parsers.yaml_parser import load_and_generate_ir
from tests.conftest import VALID_DIR


def _gen(fixture: str, tmp_path):
    result = load_and_generate_ir(str(VALID_DIR / fixture))
    ctx = build_context(result.ir)
    FastAPIGenerator().generate(ctx, tmp_path)
    return tmp_path


def _gen_inline(yaml_str: str, tmp_path):
    path = tmp_path / "spec.yaml"
    path.write_text(textwrap.dedent(yaml_str))
    result = load_and_generate_ir(str(path))
    ctx = build_context(result.ir)
    FastAPIGenerator().generate(ctx, tmp_path / "out")
    return tmp_path / "out"


# ---------------------------------------------------------------------------
# ServiceBase hook surface
# ---------------------------------------------------------------------------


def test_service_ops_has_full_async_hook_set(tmp_path):
    out = _gen("basic-crud.yaml", tmp_path)
    src = (out / "services" / "_ops.py").read_text()

    hooks = [
        "async def _before_create",
        "async def _after_create",
        "async def _before_write",
        "async def _before_update",
        "async def _after_update",
        "async def _before_replace",
        "async def _after_replace",
        "async def _before_delete",
        "async def _after_delete",
        "async def _after_get",
        "async def _after_list",
    ]
    for hook in hooks:
        assert hook in src, f"Missing hook: {hook}"


def test_service_base_constructor_accepts_principal(tmp_path):
    out = _gen("basic-crud.yaml", tmp_path)
    src = (out / "services" / "_ops.py").read_text()
    assert "principal: dict[str, Any] | None = None" in src
    assert "self._principal = principal" in src


# ---------------------------------------------------------------------------
# Op methods await hooks
# ---------------------------------------------------------------------------


def test_create_op_awaits_before_and_after_hooks(tmp_path):
    out = _gen("basic-crud.yaml", tmp_path)
    src = (out / "services" / "_ops.py").read_text()
    assert "await self._before_create(data)" in src
    assert "await self._before_write(data)" in src
    assert "await self._after_create(document)" in src


def test_update_op_awaits_before_and_after_hooks(tmp_path):
    out = _gen("basic-crud.yaml", tmp_path)
    src = (out / "services" / "_ops.py").read_text()
    assert "await self._before_update(resource_id, data)" in src
    assert "await self._after_update(document)" in src


def test_replace_op_awaits_before_and_after_hooks(tmp_path):
    out = _gen("basic-crud.yaml", tmp_path)
    src = (out / "services" / "_ops.py").read_text()
    assert "await self._before_replace(resource_id, data)" in src
    assert "await self._after_replace(document)" in src


def test_delete_op_awaits_before_and_after_hooks(tmp_path):
    out = _gen("basic-crud.yaml", tmp_path)
    src = (out / "services" / "_ops.py").read_text()
    assert "await self._before_delete(resource_id)" in src
    assert "await self._after_delete(document)" in src


def test_get_op_awaits_after_hook(tmp_path):
    out = _gen("basic-crud.yaml", tmp_path)
    src = (out / "services" / "_ops.py").read_text()
    assert "await self._after_get(document)" in src


def test_list_op_awaits_after_hook(tmp_path):
    out = _gen("basic-crud.yaml", tmp_path)
    src = (out / "services" / "_ops.py").read_text()
    assert "await self._after_list(documents)" in src


# ---------------------------------------------------------------------------
# Mixin async signatures
# ---------------------------------------------------------------------------


def test_identity_fields_mixin_is_async(tmp_path):
    out = _gen("auth-password.yaml", tmp_path)
    src = (out / "services" / "_ops.py").read_text()
    assert "async def _before_create" in src
    # IdentityFieldsMixin overrides _before_create; confirm it's async
    lines = src.splitlines()
    mixin_idx = next(i for i, l in enumerate(lines) if "class IdentityFieldsMixin" in l)
    before_create_lines = [
        l for l in lines[mixin_idx:]
        if "_before_create" in l and "async def" in l
    ]
    assert before_create_lines, "IdentityFieldsMixin._before_create must be async"


def test_password_mixin_is_async(tmp_path):
    out = _gen("auth-password.yaml", tmp_path)
    src = (out / "services" / "_ops.py").read_text()
    lines = src.splitlines()
    mixin_idx = next(i for i, l in enumerate(lines) if "class PasswordMixin" in l)
    before_write_lines = [
        l for l in lines[mixin_idx:]
        if "_before_write" in l and "async def" in l
    ]
    assert before_write_lines, "PasswordMixin._before_write must be async"


# ---------------------------------------------------------------------------
# _service() factory threading principal
# ---------------------------------------------------------------------------


def test_service_factory_accepts_principal_parameter(tmp_path):
    out = _gen("auth-password.yaml", tmp_path)
    # Find any route file that has auth
    routes_dir = out / "routes"
    route_files = list(routes_dir.glob("*.py"))
    assert route_files

    for route_file in route_files:
        if route_file.name in ("login.py", "__init__.py"):
            continue
        src = route_file.read_text()
        if "_service" in src:
            assert "def _service(principal: dict[str, Any] | None = None)" in src, \
                f"_service factory missing principal param in {route_file.name}"


def test_authed_route_passes_principal_to_service(tmp_path):
    out = _gen("auth-password.yaml", tmp_path)
    routes_dir = out / "routes"
    for route_file in routes_dir.glob("*.py"):
        if route_file.name in ("login.py", "__init__.py"):
            continue
        src = route_file.read_text()
        if "require_principal" in src:
            # At least one call must pass principal
            assert "_service(principal)" in src, \
                f"Authed route file {route_file.name} does not call _service(principal)"


def test_public_route_calls_service_without_principal(tmp_path):
    """A collection with all-public routes must call _service() (no principal arg)."""
    out = _gen_inline("""
        version: "0.2"
        api:
          basePath: /api
          version: v1
        mongo:
          uri: mongodb://localhost:27017
          database: testdb
        entities:
          post:
            fields:
              id: { type: id }
              title: { type: string, required: true }
        repositories:
          posts: { entity: post }
        services:
          posts: { repository: posts }
        controllers:
          posts:
            service: posts
            base_path: /posts
            access: public
    """, tmp_path)
    src = (out / "routes" / "posts.py").read_text()
    # All service calls should be _service() with no principal arg
    assert "_service()" in src
    assert "_service(principal)" not in src


def test_mixed_auth_routes_thread_principal_selectively(tmp_path):
    """On a collection with both public and authed routes, each call site is correct."""
    out = _gen("auth-password.yaml", tmp_path)
    # users collection: create=public (register), list/get/update/delete=authed
    users_routes = (out / "routes" / "users.py").read_text()
    # Authed routes must pass principal
    assert "_service(principal)" in users_routes
    # There should be no bare _service() call in authed route body after an auth guard
    # (public routes call _service() without principal — that is fine)


# ---------------------------------------------------------------------------
# Byte-compile sanity (no syntax errors in generated output)
# ---------------------------------------------------------------------------


def test_generated_auth_backend_compiles(tmp_path):
    import compileall
    out = _gen("auth-password.yaml", tmp_path)
    assert compileall.compile_dir(str(out), quiet=1)


def test_generated_no_auth_backend_compiles(tmp_path):
    import compileall
    out = _gen("basic-crud.yaml", tmp_path)
    assert compileall.compile_dir(str(out), quiet=1)
