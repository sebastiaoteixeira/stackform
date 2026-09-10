"""Authorization pipeline steps for role-based and condition-based access control."""

from . import NotFoundError, Step

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

_RECORD_NOT_FOUND = "Resource not found"


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
    if any(not binding.where for binding in rule.document_symbols.values()):
        return True
    if rule.when and _when_needs_document(rule.when):
        return True
    return False


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
    symbols: dict[str, dict | None] = {}
    for symbol_name in rule.identity_symbols:
        symbols[symbol_name] = principal
    return symbols


def _resolve_document_symbols(
    rule: RuntimeAccessRule,
    document: dict | None,
    where_documents: dict[str, object | None],
) -> dict[str, dict | None]:
    symbols: dict[str, dict | None] = {}
    for symbol_name, binding in rule.document_symbols.items():
        symbols[symbol_name] = (
            where_documents.get(symbol_name) if binding.where else document
        )
    return symbols


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
    symbols: dict[str, object | None] = {}
    for symbol_name, binding in rule.request_symbols.items():
        symbols[symbol_name] = (
            request_object.get(binding.part)
            if binding.part in _REQUEST_PARTS
            else request_object
        )
    return symbols


def _evaluate_rule(
    rule: RuntimeAccessRule,
    principal: dict | None,
    document: dict | None,
    ctx: RequestContext,
) -> bool:
    if rule.when is None:
        return True

    symbols: dict[str, object | None] = {
        **_resolve_identity_symbols(rule, principal),
        **_resolve_document_symbols(rule, document, ctx.where_documents or {}),
        **_resolve_request_symbols(rule, ctx),
    }
    return evaluate_when_with_symbols(rule.when, symbols)


def _where_namespace(
    rule: RuntimeAccessRule,
    ctx: RequestContext,
) -> dict[str, object | None]:
    namespace: dict[str, object | None] = dict(ctx.url_params)
    for symbol_name in rule.identity_symbols:
        namespace[symbol_name] = ctx.principal
    request_object = _request_object(ctx)
    for symbol_name, binding in rule.request_symbols.items():
        namespace[symbol_name] = (
            request_object.get(binding.part)
            if binding.part in _REQUEST_PARTS
            else request_object
        )
    return namespace


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


def ResolveWhereBindingsStep(
    access_rules: list[RuntimeAccessRule] | None = None,
) -> Step:
    async def step(ctx: RequestContext) -> RequestContext:
        if ctx.principal is None or not access_rules:
            return ctx

        where_documents: dict[str, object | None] = dict(ctx.where_documents or {})
        for rule in access_rules:
            namespace = _where_namespace(rule, ctx)
            for symbol_name, binding in rule.document_symbols.items():
                if not binding.where:
                    continue
                criteria = _where_criteria(binding.where, namespace)
                repository = ctx.repository_for(binding.collection)
                record = await repository.find_one(binding.collection, criteria)
                if record is None:
                    raise NotFoundError(_RECORD_NOT_FOUND)
                where_documents[symbol_name] = record

        ctx.where_documents = where_documents
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

        for rule in access_rules:
            if _rule_needs_postfetch(rule):
                return ctx

            if not _rule_matches_principal(rule, ctx.principal, auth_config):
                continue

            matched = _evaluate_rule(rule, ctx.principal, None, ctx)
            if matched:
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
        for rule in access_rules:
            if not _rule_matches_principal(rule, ctx.principal, auth_config):
                continue

            doc = document if _rule_needs_postfetch(rule) else None
            matched = _evaluate_rule(rule, ctx.principal, doc, ctx)
            if matched:
                if rule.effect == "deny":
                    raise ForbiddenError("Forbidden")
                return ctx

        raise ForbiddenError("Forbidden")

    return step


IdentityStep = ValidateIdentityCreateStep
