import json
import re
from dataclasses import dataclass

from shared_route_table import ROUTES


BODY_OPERATIONS = {"create", "patch", "replace"}


@dataclass(frozen=True)
class RoutePlan:
    method: str
    path_template: str
    path_regex: re.Pattern[str]
    collection: str
    operation: str
    requires_auth: bool
    admin_only: bool


def _template_to_regex(path_template: str) -> re.Pattern[str]:
    pattern = re.sub(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}", r"(?P<\1>[^/]+)", path_template)
    return re.compile(f"^{pattern}$")


def _compile_route_plans() -> list[RoutePlan]:
    plans: list[RoutePlan] = []
    for route in ROUTES:
        collection = route["path"].strip("/").split("/")[0]
        path_template = route["path"]
        path_regex = _template_to_regex(path_template)

        for method in route["methods"]:
            operation = route["operations"][method]
            requires_auth = operation != "create"
            admin_only = operation != "create"
            plans.append(
                RoutePlan(
                    method=method,
                    path_template=path_template,
                    path_regex=path_regex,
                    collection=collection,
                    operation=operation,
                    requires_auth=requires_auth,
                    admin_only=admin_only,
                )
            )
    return plans


ROUTE_PLANS = _compile_route_plans()


def _decode_principal(authorization: str | None) -> dict | None:
    if authorization == "Bearer demo-admin-token":
        return {"sub": "u1", "roles": ["admin"]}
    if authorization == "Bearer demo-user-token":
        return {"sub": "u2", "roles": ["user"]}
    return None


def _parse_json_object(body_bytes: bytes) -> dict:
    if not body_bytes:
        raise ValueError("Request body must be a JSON object")

    try:
        payload = json.loads(body_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("Request body must be valid JSON") from error

    if not isinstance(payload, dict):
        raise ValueError("Request body must be a JSON object")

    return payload


def _validate_create_payload(payload: dict) -> None:
    required_fields = ["email", "password", "displayName"]
    missing_fields = []
    for field in required_fields:
        value = payload.get(field)
        if not isinstance(value, str) or not value.strip():
            missing_fields.append(field)
    if missing_fields:
        raise ValueError(f"Missing required fields: {', '.join(missing_fields)}")


def execute(
    method: str, path: str, headers: dict[str, str], body_bytes: bytes
) -> tuple[int, dict]:
    upper_method = method.upper()
    route_plan = None
    path_params: dict[str, str] = {}

    for candidate in ROUTE_PLANS:
        if candidate.method != upper_method:
            continue
        match = candidate.path_regex.match(path)
        if match:
            route_plan = candidate
            path_params = match.groupdict()
            break

    if route_plan is None:
        return 404, {"error": "Not found"}

    authorization = headers.get("authorization") or headers.get("Authorization")
    principal = _decode_principal(authorization)

    if route_plan.requires_auth and principal is None:
        return 401, {"error": "Unauthorized"}

    if route_plan.admin_only and "admin" not in principal.get("roles", []):
        return 403, {"error": "Admin role required"}

    payload = None
    if route_plan.operation in BODY_OPERATIONS:
        try:
            payload = _parse_json_object(body_bytes)
            if route_plan.operation == "create":
                _validate_create_payload(payload)
        except ValueError as error:
            return 422, {"error": str(error)}

    return 200, {
        "collection": route_plan.collection,
        "operation": route_plan.operation,
        "id": path_params.get("id"),
        "principal": principal,
        "payload": payload,
    }
