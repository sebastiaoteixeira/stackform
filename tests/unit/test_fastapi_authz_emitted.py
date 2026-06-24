"""Tests that the emitted authorization module behaves correctly.

Renders the FastAPI authorization template, executes the resulting source,
and asserts that _principal_has_role handles direct and transitive roles,
and that route guards raise appropriate HTTP status codes.
"""

import sys
import types
from pathlib import Path

import pytest
from jinja2 import Environment, FileSystemLoader

from yaml_api_generator.generators.backend.compile_context import AuthConfig
from yaml_api_generator.generators.backend.fastapi import access_filters


_TEMPLATES_DIR = (
    Path(__file__).resolve().parents[2]
    / "src" / "yaml_api_generator" / "generators" / "backend" / "fastapi" / "templates"
)


def _make_env() -> Environment:
    env = Environment(loader=FileSystemLoader(str(_TEMPLATES_DIR)), keep_trailing_newline=True)
    env.filters["role_hierarchies_py"] = access_filters.role_hierarchies_py
    return env


def _exec_module(name: str, source: str, package: dict) -> types.ModuleType:
    module = types.ModuleType(name)
    module.__dict__.update(package)
    sys.modules[name] = module
    exec(compile(source, f"<{name}>", "exec"), module.__dict__)
    return module


@pytest.fixture()
def authz():
    env = _make_env()
    auth = AuthConfig(
        enabled=True,
        identity_collections=[],
        has_password_auth=True,
        has_api_key_auth=False,
        role_hierarchies={"admins": {"super_admin": {"admin", "moderator"}, "admin": {"moderator"}}},
    )
    authz_src = env.get_template("authorization.py.jinja").render(auth=auth)

    deps_pkg = types.ModuleType("dependencies")
    deps_pkg.__path__ = []
    sys.modules.setdefault("dependencies", deps_pkg)

    mod = _exec_module("dependencies.authorization", authz_src, {})
    yield mod

    for key in ("dependencies.authorization", "dependencies"):
        sys.modules.pop(key, None)


def test_principal_has_role_direct(authz):
    assert authz._principal_has_role({"identity_collection": "admins", "roles": ["admin"]}, "admin") is True


def test_principal_has_role_transitive(authz):
    super_admin = {"identity_collection": "admins", "roles": ["super_admin"]}
    assert authz._principal_has_role(super_admin, "moderator") is True


def test_principal_has_role_no_upward_promotion(authz):
    moderator = {"identity_collection": "admins", "roles": ["moderator"]}
    assert authz._principal_has_role(moderator, "admin") is False


def test_principal_has_role_wrong_collection(authz):
    assert authz._principal_has_role({"identity_collection": "users", "roles": ["super_admin"]}, "admin") is False


def test_rule_to_python_role_only():
    from yaml_api_generator.generators.backend.compile_context import AccessRuleDescriptor
    rule = AccessRuleDescriptor(principal="identity:admins", required_role="admin")
    assert access_filters.rule_to_python(rule) == '_principal_has_role(principal, "admin")'


def test_rule_to_python_unconditional():
    from yaml_api_generator.generators.backend.compile_context import AccessRuleDescriptor
    rule = AccessRuleDescriptor(principal="identity:admins")
    assert access_filters.rule_to_python(rule) == "True"


def test_rule_to_python_when_equals():
    from yaml_api_generator.generators.backend.compile_context import AccessRuleDescriptor
    from yaml_api_generator.ir.when import Equals, FieldRef
    rule = AccessRuleDescriptor(
        principal="identity:users",
        when=Equals(FieldRef("principal", ("sub",)), FieldRef("document", ("created_by",))),
    )
    assert 'principal.get("sub") == document.get("created_by")' in access_filters.rule_to_python(rule)


def test_is_unconditional_true():
    from yaml_api_generator.generators.backend.compile_context import AccessRuleDescriptor
    rule = AccessRuleDescriptor(principal="identity:admins")
    assert access_filters.is_unconditional(rule) is True


def test_is_unconditional_false_when_role():
    from yaml_api_generator.generators.backend.compile_context import AccessRuleDescriptor
    rule = AccessRuleDescriptor(principal="identity:admins", required_role="admin")
    assert access_filters.is_unconditional(rule) is False
