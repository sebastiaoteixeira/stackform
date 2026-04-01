from . import Step

from ..context import RequestContext

from ..runtime_context import RuntimeAccessRule, RuntimeAuthConfig, RuntimeIdentityDescriptor
from ..when_eval import evaluate_when, needs_document


class UnauthorizedError(ValueError):
    pass


class ForbiddenError(ValueError):
    pass


def _required_identity_fields(
    identity_collection: RuntimeIdentityDescriptor,
) -> tuple[str, ...]:
    fields: list[str] = []
    if identity_collection.identifier:
        fields.append(identity_collection.identifier)

    for method in identity_collection.via:
        if method == "password":
            fields.append("password")
        elif method == "apiKey":
            fields.append("apiKey")
        else:
            raise ValueError(f"Unsupported auth method: {method}")

    unique_fields: list[str] = []
    for field_name in fields:
        if field_name and field_name not in unique_fields:
            unique_fields.append(field_name)
    return tuple(unique_fields)


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
    return rule.when is not None and needs_document(rule.when)


def _principal_has_role(
    principal: dict,
    required_role: str,
    auth_config: RuntimeAuthConfig | None,
) -> bool:
    """Check if principal has the required role, considering hierarchy."""
    principal_roles = principal.get("roles", [])
    if required_role in principal_roles:
        return True

    if auth_config is None:
        return False

    # Check hierarchy: principal's roles may include required_role transitively
    identity_collection = principal.get("identity_collection", "")
    # entity name = collection name without trailing 's'
    entity_name = identity_collection.rstrip("s") if identity_collection.endswith("s") else identity_collection
    entity_hierarchy = auth_config.role_hierarchies.get(entity_name, {})

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
    """Check if the rule's principal/role constraints match the current principal."""
    if principal is None:
        return False

    # If rule has a principal constraint (e.g. identity:users), check it
    if rule.principal and rule.principal.startswith("identity:"):
        expected_collection = rule.principal[len("identity:"):]
        if principal.get("identity_collection") != expected_collection:
            return False

    # If rule requires a specific role, check it
    if rule.required_role is not None:
        if not _principal_has_role(principal, rule.required_role, auth_config):
            return False

    return True


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
                return ctx  # defer to PostFetchAuthorizeStep

            if not _rule_matches_principal(rule, ctx.principal, auth_config):
                continue

            matched = rule.when is None or evaluate_when(rule.when, ctx.principal, None)
            if matched:
                if rule.effect == "deny":
                    raise ForbiddenError("Forbidden")
                return ctx  # allow

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
            matched = rule.when is None or evaluate_when(rule.when, ctx.principal, doc)
            if matched:
                if rule.effect == "deny":
                    raise ForbiddenError("Forbidden")
                return ctx  # allow

        raise ForbiddenError("Forbidden")

    return step


IdentityStep = ValidateIdentityCreateStep
