"""Authorization pipeline steps for access control.

Enforces role-based and condition-based authorization rules.
Supports pre-fetch and post-fetch authorization for fine-grained control.

Authorization steps:
- AuthorizeRouteStep(): Check authorization before repository access
- PostFetchAuthorizeStep(): Check authorization after fetching document
- ValidateIdentityCreateStep(): Ensure identity creation includes required fields

Access rules support:
- Role requirements with hierarchy (admin > editor > viewer)
- Identity collection filtering (identity:users)
- 'when' expressions (principal.role equals 'admin')
- Document-dependent conditions (principal.id equals document.owner_id)
- Allow/deny effects

Exceptions:
- UnauthorizedError: No authentication (401)
- ForbiddenError: Authenticated but not authorized (403)
"""

from . import Step

from ..request_context import RequestContext

from ..server_context import (
    RuntimeAccessRule,
    RuntimeAuthConfig,
    RuntimeIdentityDescriptor,
)
from ..when_eval import evaluate_when, evaluate_when_with_symbols
from yaml_api_generator.ir.when import collect_roots, needs_document as _when_needs_document


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


def _rule_needs_document(rule: RuntimeAccessRule) -> bool:
    if rule.document_symbols:
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
) -> dict[str, dict | None]:
    symbols: dict[str, dict | None] = {}
    for symbol_name in rule.document_symbols:
        symbols[symbol_name] = document
    return symbols


def _evaluate_rule(
    rule: RuntimeAccessRule,
    principal: dict | None,
    document: dict | None,
) -> bool:
    if rule.when is None:
        return True

    if rule.identity_symbols or rule.document_symbols:
        symbols: dict[str, dict | None] = {}
        if principal is not None:
            symbols["principal"] = principal
        symbols.update(_resolve_identity_symbols(rule, principal))
        symbols.update(_resolve_document_symbols(rule, document))
        return evaluate_when_with_symbols(rule.when, symbols)

    return evaluate_when(rule.when, principal, document)


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
            if _rule_needs_document(rule):
                return ctx

            if not _rule_matches_principal(rule, ctx.principal, auth_config):
                continue

            matched = _evaluate_rule(rule, ctx.principal, None)
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

            doc = document if _rule_needs_document(rule) else None
            matched = _evaluate_rule(rule, ctx.principal, doc)
            if matched:
                if rule.effect == "deny":
                    raise ForbiddenError("Forbidden")
                return ctx

        raise ForbiddenError("Forbidden")

    return step


IdentityStep = ValidateIdentityCreateStep
