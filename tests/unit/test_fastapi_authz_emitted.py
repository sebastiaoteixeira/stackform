"""Tests that the emitted when_eval / authorization modules behave correctly.

Renders the FastAPI templates, executes the resulting source, and asserts the
emitted evaluator matches the run-server evaluator on a shared AST corpus, plus
exercises the emitted authorization helpers (401/403/404 ordering, identity and
role matching, document deferral).
"""

import sys
import types
from pathlib import Path

import pytest
from jinja2 import Environment, FileSystemLoader

from yaml_api_generator.generators.backend.compile_context import AuthConfig
from yaml_api_generator.generators.backend.fastapi import access_filters
from yaml_api_generator.ir.when import And, Equals, FieldRef, In, Not, NotEquals, NotIn, Or, StringLiteral
from yaml_api_generator.server.common.when_eval import evaluate_when_with_symbols as run_evaluate


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
def emitted(monkeypatch):
    env = _make_env()
    when_src = env.get_template("when_eval.py.jinja").render()
    when_eval = _exec_module("dependencies.when_eval", when_src, {})

    deps_pkg = types.ModuleType("dependencies")
    deps_pkg.__path__ = []
    sys.modules.setdefault("dependencies", deps_pkg)
    sys.modules["dependencies.when_eval"] = when_eval

    auth = AuthConfig(
        enabled=True,
        identity_collections=[],
        has_password_auth=True,
        has_api_key_auth=False,
        role_hierarchies={"admins": {"super_admin": {"admin", "moderator"}, "admin": {"moderator"}}},
    )
    authz_src = env.get_template("authorization.py.jinja").render(auth=auth)
    authz = _exec_module("dependencies.authorization", authz_src, {})

    yield when_eval, authz

    for mod in ("dependencies.authorization", "dependencies.when_eval", "dependencies"):
        sys.modules.pop(mod, None)


def _translate(expr, when_eval):
    """Rebuild an IR when-expr using the emitted module's classes."""
    cls = getattr(when_eval, type(expr).__name__)
    if isinstance(expr, FieldRef):
        return cls(expr.root, tuple(expr.path))
    if isinstance(expr, StringLiteral):
        return cls(expr.value)
    if isinstance(expr, (Equals, NotEquals, And, Or)):
        return cls(_translate(expr.left, when_eval), _translate(expr.right, when_eval))
    if isinstance(expr, Not):
        return cls(_translate(expr.operand, when_eval))
    if isinstance(expr, (In, NotIn)):
        return cls(_translate(expr.left, when_eval), tuple(expr.values))
    raise TypeError(type(expr).__name__)


_CORPUS = [
    Equals(FieldRef("principal", ("sub",)), FieldRef("document", ("id",))),
    NotEquals(FieldRef("principal", ("record", "role")), StringLiteral("guest")),
    And(
        Equals(FieldRef("principal", ()), FieldRef("document", ("owner",))),
        NotEquals(FieldRef("principal", ("role",)), StringLiteral("banned")),
    ),
    Or(Equals(FieldRef("principal", ("role",)), StringLiteral("admin")), Not(Equals(FieldRef("principal", ("sub",)), StringLiteral("x")))),
    In(FieldRef("principal", ("role",)), ("admin", "moderator")),
    NotIn(FieldRef("principal", ("role",)), ("guest",)),
]

_SYMBOL_CASES = [
    {"principal": {"sub": "u1", "role": "admin", "record": {"role": "admin"}}, "document": {"id": "u1", "owner": "u1"}},
    {"principal": {"sub": "u2", "role": "guest", "record": {"role": "guest"}}, "document": {"id": "u1", "owner": "u9"}},
    {"principal": None, "document": None},
]


@pytest.mark.parametrize("expr", _CORPUS)
@pytest.mark.parametrize("symbols", _SYMBOL_CASES)
def test_emitted_evaluator_matches_run_server(emitted, expr, symbols):
    when_eval, _ = emitted
    emitted_expr = _translate(expr, when_eval)
    assert when_eval.evaluate_when_with_symbols(emitted_expr, symbols) == run_evaluate(expr, symbols)


def test_emitted_in_notin_evaluate_per_membership(emitted):
    when_eval, _ = emitted
    expr = when_eval.In(when_eval.FieldRef("principal", ("role",)), ("admin",))
    assert when_eval.evaluate_when_with_symbols(expr, {"principal": {"role": "admin"}}) is True
    assert when_eval.evaluate_when_with_symbols(expr, {"principal": {"role": "user"}}) is False


def _http_status(func, *args):
    from fastapi import HTTPException

    try:
        func(*args)
    except HTTPException as exc:
        return exc.status_code
    return None


def test_principal_has_role_direct_and_transitive(emitted):
    _, authz = emitted
    super_admin = {"identity_collection": "admins", "roles": ["super_admin"]}
    assert authz._principal_has_role(super_admin, "super_admin") is True
    assert authz._principal_has_role(super_admin, "moderator") is True  # transitive
    assert authz._principal_has_role({"identity_collection": "admins", "roles": ["moderator"]}, "admin") is False


def test_rule_matches_principal_identity_and_role(emitted):
    _, authz = emitted
    rule = authz.AccessRule(principal="identity:admins", required_role="admin")
    assert authz._rule_matches_principal(rule, {"identity_collection": "admins", "roles": ["super_admin"]}) is True
    assert authz._rule_matches_principal(rule, {"identity_collection": "users", "roles": ["super_admin"]}) is False
    assert authz._rule_matches_principal(rule, {"identity_collection": "admins", "roles": ["moderator"]}) is False
    assert authz._rule_matches_principal(rule, None) is False


def test_authorize_pre_unauthenticated_401(emitted):
    _, authz = emitted
    assert _http_status(authz.authorize_pre, [], None) == 401


def test_authorize_pre_no_rules_allows(emitted):
    _, authz = emitted
    assert authz.authorize_pre([], {"identity_collection": "admins", "roles": []}) is None


def test_authorize_pre_default_deny_403(emitted):
    _, authz = emitted
    rule = authz.AccessRule(principal="identity:admins", required_role="admin")
    assert _http_status(authz.authorize_pre, [rule], {"identity_collection": "admins", "roles": ["support"]}) == 403


def test_authorize_pre_deny_short_circuits(emitted):
    _, authz = emitted
    rule = authz.AccessRule(principal="identity:admins", effect="deny")
    assert _http_status(authz.authorize_pre, [rule], {"identity_collection": "admins", "roles": []}) == 403


def test_authorize_pre_document_rule_defers(emitted):
    _, authz = emitted
    doc_rule = authz.AccessRule(principal="identity:admins", document_symbols=["document"])
    assert authz.authorize_pre([doc_rule], {"identity_collection": "admins", "roles": []}) is None


def test_authorize_post_owner_allow_and_default_deny(emitted):
    when_eval, authz = emitted
    rule = authz.AccessRule(
        principal="identity:users",
        identity_symbols=["principal"],
        document_symbols=["document"],
        when=when_eval.Equals(when_eval.FieldRef("principal", ("sub",)), when_eval.FieldRef("document", ("created_by",))),
    )
    owner = {"identity_collection": "users", "sub": "u1", "roles": []}
    assert authz.authorize_post([rule], owner, {"created_by": "u1"}) is None
    assert _http_status(authz.authorize_post, [rule], owner, {"created_by": "u2"}) == 403


def test_authorize_post_none_document_allows(emitted):
    _, authz = emitted
    rule = authz.AccessRule(principal="identity:users", document_symbols=["document"])
    assert authz.authorize_post([rule], {"identity_collection": "users", "roles": []}, None) is None
