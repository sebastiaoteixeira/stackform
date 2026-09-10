"""Authorization pipeline steps for role-based and condition-based access control."""

from collections.abc import Iterable
from itertools import repeat

from . import Step

from ..request_context import RequestContext

from ..server_context import (
    RuntimeAccessRule,
    RuntimeAuthConfig,
    RuntimeIdentityDescriptor,
)
from ..when_eval import evaluate_when_with_symbols
from ..utils.field_access import get_nested_field
from yaml_api_generator.ir.api import IRLiteralRef, IRSymbolRef, IRWhereConjunct
from yaml_api_generator.ir.when import needs_document as _when_needs_document

WhereDocuments = dict[str, dict | None]


class UnauthorizedError(ValueError):
    pass


class ForbiddenError(ValueError):
    pass


def _required_identity_fields(
    identity_collection: RuntimeIdentityDescriptor,
) -> tuple[str, ...]:
    seen: set[str] = set()
    fields: list[str] = []

    for binding in identity_collection.bindings:
        if binding.identifier and binding.identifier not in seen:
            fields.append(binding.identifier)
            seen.add(binding.identifier)
        if binding.provider not in seen:
            fields.append(binding.provider)
            seen.add(binding.provider)

    return tuple(fields)


def ValidateIdentityCreateStep(
    identity_collection: RuntimeIdentityDescriptor,
) -> Step:
    required_fields = _required_identity_fields(identity_collection)

    def step(ctx: RequestContext) -> RequestContext:
        if ctx.collection != identity_collection.name or ctx.operation != "create":
            return ctx
        if not isinstance(ctx.body, dict):
            raise ValueError("Request body must be a JSON object")
        missing_fields = [
            field_name
            for field_name in required_fields
            if not isinstance(ctx.body.get(field_name), str)
            or not ctx.body[field_name].strip()
        ]
        if missing_fields:
            raise ValueError(f"Missing required fields: {', '.join(missing_fields)}")
        return ctx

    return step


def _rule_needs_postfetch(rule: RuntimeAccessRule) -> bool:
    return any(not binding.where for binding in rule.document_symbols.values()) or (
        rule.when is not None and _when_needs_document(rule.when)
    )


def _principal_has_role(
    principal: dict,
    required_role: str,
    auth_config: RuntimeAuthConfig | None,
) -> bool:
    principal_roles = principal.get("roles", [])
    if required_role in principal_roles:
        return True

    if auth_config is None:
        return False

    identity_collection = principal.get("identity_collection", "")
    entity_hierarchy = auth_config.role_hierarchies.get(identity_collection, {})

    for role in principal_roles:
        included = entity_hierarchy.get(role, set())
        if required_role in included:
            return True

    return False


def _rule_matches_principal(
    rule: RuntimeAccessRule,
    principal: dict | None,
    auth_config: RuntimeAuthConfig | None,
) -> bool:
    if principal is None:
        return False

    if rule.principal and rule.principal.startswith("identity:"):
        expected_collection = rule.principal[len("identity:"):]
        if principal.get("identity_collection") != expected_collection:
            return False

    if rule.required_role is not None:
        if not _principal_has_role(principal, rule.required_role, auth_config):
            return False

    return True


def _resolve_identity_symbols(
    rule: RuntimeAccessRule,
    principal: dict | None,
) -> dict[str, dict | None]:
    return {symbol_name: principal for symbol_name in rule.identity_symbols}


def _resolve_document_symbols(
    rule: RuntimeAccessRule,
    document: dict | None,
    where_documents: WhereDocuments,
) -> dict[str, dict | None]:
    return {
        symbol_name: where_documents.get(symbol_name) if binding.where else document
        for symbol_name, binding in rule.document_symbols.items()
    }


_REQUEST_PARTS = ("body", "path", "query", "header", "cookie")


def _request_object(ctx: RequestContext) -> dict[str, object | None]:
    return {
        "body": ctx.body,
        "path": ctx.url_params,
        "query": ctx.query,
        "header": ctx.headers,
        "cookie": ctx.cookies,
    }


def _resolve_request_symbols(
    rule: RuntimeAccessRule,
    ctx: RequestContext,
) -> dict[str, object | None]:
    request_object = _request_object(ctx)
    return {
        symbol_name: (
            request_object.get(binding.part)
            if binding.part in _REQUEST_PARTS
            else request_object
        )
        for symbol_name, binding in rule.request_symbols.items()
    }


def _where_documents_found(
    rule: RuntimeAccessRule,
    where_documents: WhereDocuments,
) -> bool:
    return all(
        where_documents.get(symbol_name) is not None
        for symbol_name, binding in rule.document_symbols.items()
        if binding.where
    )


def _evaluate_rule(
    rule: RuntimeAccessRule,
    document: dict | None,
    where_documents: WhereDocuments,
    ctx: RequestContext,
) -> bool:
    if not _where_documents_found(rule, where_documents):
        return False
    if rule.when is None:
        return True

    symbols: dict[str, object | None] = {
        **_resolve_identity_symbols(rule, ctx.principal),
        **_resolve_document_symbols(rule, document, where_documents),
        **_resolve_request_symbols(rule, ctx),
    }
    return evaluate_when_with_symbols(rule.when, symbols)


def _rules_with_where_documents(
    access_rules: list[RuntimeAccessRule],
    ctx: RequestContext,
) -> Iterable[tuple[RuntimeAccessRule, WhereDocuments]]:
    return zip(access_rules, ctx.where_documents or repeat({}))


def _where_namespace(
    rule: RuntimeAccessRule,
    ctx: RequestContext,
) -> dict[str, object | None]:
    return {
        **ctx.url_params,
        **_resolve_identity_symbols(rule, ctx.principal),
        **_resolve_request_symbols(rule, ctx),
    }


def _rhs_value(
    rhs: IRSymbolRef | IRLiteralRef,
    namespace: dict[str, object | None],
) -> object | None:
    if isinstance(rhs, IRLiteralRef):
        return rhs.value
    base = namespace.get(rhs.root)
    if not rhs.path:
        return base
    if not isinstance(base, dict):
        return None
    return get_nested_field(base, ".".join(rhs.path))


def _where_criteria(
    conjuncts: tuple[IRWhereConjunct, ...],
    namespace: dict[str, object | None],
) -> dict[str, object | None]:
    return {conjunct.field: _rhs_value(conjunct.rhs, namespace) for conjunct in conjuncts}


async def _where_documents(rule: RuntimeAccessRule, ctx: RequestContext) -> WhereDocuments:
    namespace = _where_namespace(rule, ctx)
    return {
        symbol_name: await ctx.repository_for(binding.collection).find_one(
            binding.collection, _where_criteria(binding.where, namespace)
        )
        for symbol_name, binding in rule.document_symbols.items()
        if binding.where
    }


def ResolveWhereBindingsStep(access_rules: list[RuntimeAccessRule]) -> Step:
    async def step(ctx: RequestContext) -> RequestContext:
        if ctx.principal is None:
            return ctx

        ctx.where_documents = [await _where_documents(rule, ctx) for rule in access_rules]
        return ctx

    return step


def AuthorizeRouteStep(
    access_rules: list[RuntimeAccessRule] | None = None,
    auth_config: RuntimeAuthConfig | None = None,
) -> Step:
    def step(ctx: RequestContext) -> RequestContext:
        if ctx.principal is None:
            raise UnauthorizedError("Unauthorized")

        if not access_rules:
            return ctx

        for rule, where_documents in _rules_with_where_documents(access_rules, ctx):
            if _rule_needs_postfetch(rule):
                return ctx

            if not _rule_matches_principal(rule, ctx.principal, auth_config):
                continue

            if _evaluate_rule(rule, None, where_documents, ctx):
                if rule.effect == "deny":
                    raise ForbiddenError("Forbidden")
                return ctx

        raise ForbiddenError("Forbidden")

    return step


def PostFetchAuthorizeStep(
    access_rules: list[RuntimeAccessRule],
    auth_config: RuntimeAuthConfig | None = None,
) -> Step:
    def step(ctx: RequestContext) -> RequestContext:
        if ctx.response is None:
            return ctx

        document = ctx.response if isinstance(ctx.response, dict) else None
        for rule, where_documents in _rules_with_where_documents(access_rules, ctx):
            if not _rule_matches_principal(rule, ctx.principal, auth_config):
                continue

            doc = document if _rule_needs_postfetch(rule) else None
            if _evaluate_rule(rule, doc, where_documents, ctx):
                if rule.effect == "deny":
                    raise ForbiddenError("Forbidden")
                return ctx

        raise ForbiddenError("Forbidden")

    return step


IdentityStep = ValidateIdentityCreateStep
