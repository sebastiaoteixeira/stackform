"""Generation tests for FastAPI access-rule enforcement.

Asserts the generator emits the authorization/when_eval dependency modules and
the per-route AccessRule literals when auth is enabled, emits nothing when auth
is disabled, and byte-compiles the generated backend.
"""

import ast
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


def test_authz_modules_emitted_when_auth_enabled(tmp_path):
    _generate("roles-access.yaml", tmp_path)
    assert (tmp_path / "dependencies" / "authorization.py").exists()
    assert (tmp_path / "dependencies" / "when_eval.py").exists()


def test_role_gated_rules_emitted_as_access_rule_literals(tmp_path):
    _generate("roles-access.yaml", tmp_path)
    posts = (tmp_path / "routes" / "posts.py").read_text()
    assert "from dependencies.authorization import AccessRule" in posts
    assert "required_role='moderator'" in posts
    assert "required_role='admin'" in posts


def test_document_rule_emits_when_ast_and_post_fetch(tmp_path):
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
    assert "access_rules" not in posts


def test_generated_backend_byte_compiles(tmp_path):
    _generate("roles-access.yaml", tmp_path)
    assert compileall.compile_dir(str(tmp_path), quiet=1)
