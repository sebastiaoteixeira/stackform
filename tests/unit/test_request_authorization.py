import pytest

from yaml_api_generator.ir import IRRequestBinding
from yaml_api_generator.ir.when import Equals, FieldRef, StringLiteral
from yaml_api_generator.server.common.request_context import RequestContext
from yaml_api_generator.server.common.server_context import RuntimeAccessRule
from yaml_api_generator.server.common.steps.authorization import (
    AuthorizeRouteStep,
    ForbiddenError,
)


_PRINCIPAL = {"sub": "u1", "identity_collection": "users", "record": {}}


def _ctx(**overrides) -> RequestContext:
    defaults = dict(
        method="POST",
        path="/memberships",
        api_version=None,
        collection="memberships",
        operation="create",
        headers={},
        url_params={},
        repository=None,
        principal=_PRINCIPAL,
        body=None,
        response=None,
    )
    defaults.update(overrides)
    return RequestContext(**defaults)


def _body_rule() -> RuntimeAccessRule:
    return RuntimeAccessRule(
        principal="identity:users",
        when=Equals(FieldRef("payload", ("body", "role")), StringLiteral("admin")),
        request_symbols={"payload": IRRequestBinding(part=None)},
    )


def _path_rule() -> RuntimeAccessRule:
    return RuntimeAccessRule(
        principal="identity:users",
        when=Equals(FieldRef("req", ("path", "orgId")), StringLiteral("org-1")),
        request_symbols={"req": IRRequestBinding(part=None)},
    )


def test_body_rule_allows_on_match():
    step = AuthorizeRouteStep(access_rules=[_body_rule()])
    result = step(_ctx(body={"role": "admin"}))
    assert result is not None


def test_body_rule_denies_on_mismatch():
    step = AuthorizeRouteStep(access_rules=[_body_rule()])
    with pytest.raises(ForbiddenError):
        step(_ctx(body={"role": "viewer"}))


def test_path_rule_allows_on_match():
    step = AuthorizeRouteStep(access_rules=[_path_rule()])
    result = step(_ctx(url_params={"orgId": "org-1"}))
    assert result is not None


def test_path_rule_denies_on_mismatch():
    step = AuthorizeRouteStep(access_rules=[_path_rule()])
    with pytest.raises(ForbiddenError):
        step(_ctx(url_params={"orgId": "org-2"}))


def test_missing_leaf_resolves_to_none_and_denies():
    step = AuthorizeRouteStep(access_rules=[_body_rule()])
    with pytest.raises(ForbiddenError):
        step(_ctx(body=None))


def test_missing_path_param_denies_without_error():
    step = AuthorizeRouteStep(access_rules=[_path_rule()])
    with pytest.raises(ForbiddenError):
        step(_ctx(url_params={}))


def _deny_rule(reason: str | None = None) -> RuntimeAccessRule:
    return RuntimeAccessRule(
        principal="identity:users",
        effect="deny",
        reason=reason,
    )


def test_matched_deny_surfaces_reason():
    step = AuthorizeRouteStep(access_rules=[_deny_rule("Only owners may act")])
    with pytest.raises(ForbiddenError, match="Only owners may act"):
        step(_ctx())


def test_matched_deny_without_reason_stays_generic():
    step = AuthorizeRouteStep(access_rules=[_deny_rule()])
    with pytest.raises(ForbiddenError, match="^Forbidden$"):
        step(_ctx())


def test_unmatched_fallthrough_stays_generic():
    step = AuthorizeRouteStep(access_rules=[_body_rule()])
    with pytest.raises(ForbiddenError, match="^Forbidden$"):
        step(_ctx(body={"role": "viewer"}))


def test_part_bound_symbol_resolves_to_part():
    rule = RuntimeAccessRule(
        principal="identity:users",
        when=Equals(FieldRef("q", ("page",)), StringLiteral("1")),
        request_symbols={"q": IRRequestBinding(part="query")},
    )
    step = AuthorizeRouteStep(access_rules=[rule])
    assert step(_ctx(query={"page": "1"})) is not None
    with pytest.raises(ForbiddenError):
        step(_ctx(query={"page": "2"}))
