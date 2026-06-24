"""Generation tests for FastAPI access-rule enforcement.

Asserts the generator emits compiled inline guards in routes (no AST interpreter),
emits nothing when auth is disabled, and byte-compiles the generated backend.
"""

import compileall
import dataclasses

from yaml_api_generator.generators.backend.context_builder import build_context
from yaml_api_generator.generators.backend.fastapi.generator import FastAPIGenerator
from yaml_api_generator.parsers.yaml_parser import load_and_generate_ir
from tests.conftest import VALID_DIR


def _generate(fixture_name: str, tmp_path, context_mutator=None):
    ctx = build_context(load_and_generate_ir(str(VALID_DIR / fixture_name)).ir)
    if context_mutator is not None:
        ctx = context_mutator(ctx)
    FastAPIGenerator().generate(ctx, tmp_path)
    return ctx


def test_when_eval_not_emitted(tmp_path):
    _generate("roles-access.yaml", tmp_path)
    assert not (tmp_path / "dependencies" / "when_eval.py").exists()


def test_authorization_module_emitted_with_role_helper(tmp_path):
    _generate("roles-access.yaml", tmp_path)
    authz = (tmp_path / "dependencies" / "authorization.py").read_text()
    assert "def _principal_has_role(" in authz
    assert "AccessRule" not in authz
    assert "authorize_pre" not in authz
    assert "authorize_post" not in authz


def test_role_gated_rules_compiled_inline(tmp_path):
    _generate("roles-access.yaml", tmp_path)
    posts = (tmp_path / "routes" / "posts.py").read_text()
    assert "AccessRule" not in posts
    assert "FieldRef" not in posts
    assert "_principal_has_role(principal," in posts


def test_document_rule_compiles_post_fetch_guard(tmp_path):
    def add_hierarchy(ctx):
        return dataclasses.replace(
            ctx,
            auth=dataclasses.replace(ctx.auth, role_hierarchies={"users": {"admin": {"moderator"}}}),
        )

    _generate("roles-access.yaml", tmp_path, add_hierarchy)
    authz = (tmp_path / "dependencies" / "authorization.py").read_text()
    assert "'users': {'admin': {'moderator'}}" in authz


def test_principal_includes_roles_extraction(tmp_path):
    _generate("roles-access.yaml", tmp_path)
    auth_module = (tmp_path / "dependencies" / "auth.py").read_text()
    assert "_extract_roles" in auth_module
    assert '"roles": _extract_roles(' in auth_module
    assert "_extract_roles(doc, 'role')" in auth_module


def test_roles_field_default_emits_python_none(tmp_path):
    import ast
    _generate("auth-password.yaml", tmp_path)
    auth_module = (tmp_path / "dependencies" / "auth.py").read_text()
    assert "_extract_roles(doc, None)" in auth_module
    names = {n.id for n in ast.walk(ast.parse(auth_module)) if isinstance(n, ast.Name)}
    assert "null" not in names


def test_no_authz_emitted_without_auth(tmp_path):
    ctx = _generate("basic-crud.yaml", tmp_path)
    assert ctx.auth.enabled is False
    assert not (tmp_path / "dependencies" / "authorization.py").exists()
    assert not (tmp_path / "dependencies" / "when_eval.py").exists()
    posts = (tmp_path / "routes" / "posts.py").read_text()
    assert "AccessRule" not in posts
    assert "_principal_has_role" not in posts


def test_generated_backend_byte_compiles(tmp_path):
    _generate("roles-access.yaml", tmp_path)
    assert compileall.compile_dir(str(tmp_path), quiet=1)
