import os
from datetime import datetime
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.openapi.utils import get_openapi
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field, create_model

from yaml_api_generator.ir.api import IROIDCProvider, IRProviderBinding
from yaml_api_generator.utils.strings import to_pascal_case
from ..common.auth import oidc
from ..common.auth.jwt import create_jwt_token
from ..common.auth.login_codes import login_codes
from ..common.server_context import (
    RuntimeAuthConfig,
    RuntimeCollectionDescriptor,
    RuntimeContext,
    RuntimeIdentityDescriptor,
    RuntimeRouteDescriptor,
)
from ..common.pipeline import Pipeline
from ..common.pipeline_builder import PipelineBuilder
from ..common.repositories import BaseRepository, RepositoryRegistry
from ..common.steps import ForbiddenError, NotFoundError, UnauthorizedError


WRITE_OPERATIONS = frozenset({"create", "update", "replace"})


def create_pydantic_model_fields(
    collection: RuntimeCollectionDescriptor,
    operation: str,
    identity_collection: RuntimeIdentityDescriptor | None = None,
) -> dict[str, tuple[Any, Any]]:
    make_optional = operation == "update"
    fields: dict[str, tuple[Any, Any]] = {}

    for field_name, raw_config in collection.fields.items():
        if not isinstance(raw_config, dict):
            continue
        if raw_config.get("type") == "id":
            continue
        if field_name == "_auth":
            continue

        annotation = _field_annotation(raw_config)
        required = bool(raw_config.get("required", False))
        has_default = "default" in raw_config
        default_value: Any

        if make_optional:
            annotation = annotation | None
            default_value = raw_config.get("default", None)
        elif has_default:
            default_value = raw_config["default"]
        elif required:
            default_value = ...
        else:
            annotation = annotation | None
            default_value = None

        field_kwargs: dict[str, Any] = {}
        if raw_config.get("min") is not None:
            field_kwargs["ge"] = raw_config["min"]
        if raw_config.get("max") is not None:
            field_kwargs["le"] = raw_config["max"]
        if raw_config.get("minLength") is not None:
            field_kwargs["min_length"] = raw_config["minLength"]
        if raw_config.get("maxLength") is not None:
            field_kwargs["max_length"] = raw_config["maxLength"]

        default: Any = (
            Field(default_value, **field_kwargs) if field_kwargs else default_value
        )
        fields[field_name] = (annotation, default)

    if (
        identity_collection is not None
        and operation == "create"
        and identity_collection.has_password
        and "password" not in fields
    ):
        fields["password"] = (str, Field(..., min_length=1))

    return fields


def create_pydantic_model(
    collection: RuntimeCollectionDescriptor,
    operation: str,
    identity_collection: RuntimeIdentityDescriptor | None = None,
) -> type[BaseModel] | None:
    if operation == "login" and identity_collection is not None:
        pw_binding = identity_collection.get_binding("password")
        identifier_field = pw_binding.identifier if pw_binding else "identifier"
        fields = {
            identifier_field: (str, Field(..., min_length=1)),
            "password": (str, Field(..., min_length=1)),
        }
        model_name = to_pascal_case(collection.name)
        return create_model(f"{model_name}LoginPayload", **fields)

    if operation not in WRITE_OPERATIONS:
        return None

    model_fields = create_pydantic_model_fields(
        collection,
        operation,
        identity_collection,
    )
    operation_suffix = operation.capitalize()
    model_name = to_pascal_case(collection.name)
    return create_model(f"{model_name}{operation_suffix}Payload", **model_fields)


def register_fastapi_routes(
    app: FastAPI,
    ctx: RuntimeContext,
    registry: RepositoryRegistry,
) -> dict[tuple[str, str], Pipeline]:
    pipelines: dict[tuple[str, str], Pipeline] = {}
    pipeline_builder = PipelineBuilder(ctx=ctx, registry=registry)

    for route in ctx.routes:
        pipeline = pipeline_builder.build_for_route(route)
        pipelines[(route.method, route.path)] = pipeline

        body_model: type[BaseModel] | None = None
        if route.handler is None and route.collection is not None:
            collection = ctx.collections[route.collection]
            identity_collection = ctx.auth.identity_collections.get(route.collection)
            body_model = create_pydantic_model(
                collection,
                route.operation,
                identity_collection,
            )

        endpoint = _build_endpoint(pipeline, body_model, route)
        security = _security_requirements(route, ctx.auth)
        openapi_extra = {"security": security} if security else None
        app.add_api_route(
            route.path,
            endpoint,
            methods=[route.method],
            openapi_extra=openapi_extra,
        )

    register_provider_routes(app, ctx, registry)
    _configure_openapi_security(app, ctx.auth)

    return pipelines


def _base_prefix(ctx: RuntimeContext) -> str:
    prefix = ctx.app.base_path
    if ctx.app.api_version:
        prefix = f"{prefix}/{ctx.app.api_version}"
    return prefix


def register_provider_routes(
    app: FastAPI,
    ctx: RuntimeContext,
    registry: RepositoryRegistry,
) -> None:
    """Mount OIDC provider routes for each identity collection that binds one.

    Reaches parity with the generated backend's oidc_routes for the dev server:
    a provider-listing endpoint, the login redirect, the callback, and the
    shared one-time-code exchange.
    """
    auth = ctx.auth
    base_prefix = _base_prefix(ctx)
    has_oidc = False

    for name, identity in auth.identity_collections.items():
        bound = [
            (binding, auth.providers.get(binding.provider))
            for binding in identity.bindings
            if auth.providers.get(binding.provider) is not None
        ]
        if not bound:
            continue

        listing = [{"name": b.provider, "type": p.type} for b, p in bound]
        app.add_api_route(
            f"{base_prefix}/{name}/auth/providers",
            _providers_listing_endpoint(listing),
            methods=["GET"],
        )

        for binding, provider in bound:
            if not isinstance(provider, IROIDCProvider):
                continue
            login_path = f"{base_prefix}/{name}/auth/{binding.provider}"
            app.add_api_route(
                f"{login_path}/logout", _oidc_logout_endpoint(provider), methods=["GET"]
            )
            if provider.is_idp:
                continue
            has_oidc = True
            collection = ctx.collections[name]
            callback_path = f"{login_path}/callback"
            app.add_api_route(
                login_path, _oidc_login_endpoint(provider, callback_path), methods=["GET"]
            )
            app.add_api_route(
                callback_path,
                _oidc_callback_endpoint(provider, binding, collection, registry, callback_path, collections=ctx.collections),
                methods=["GET"],
            )

    if has_oidc:
        app.add_api_route(f"{base_prefix}/auth/exchange", _exchange_endpoint, methods=["POST"])


def _providers_listing_endpoint(listing: list[dict[str, str]]):
    async def endpoint() -> list[dict[str, str]]:
        return listing

    return endpoint


def _oidc_login_endpoint(provider: IROIDCProvider, callback_path: str):
    async def endpoint(request: Request) -> RedirectResponse:
        callback_url = str(request.base_url).rstrip("/") + callback_path
        return RedirectResponse(url=await oidc.build_login_redirect(provider, callback_url))

    return endpoint


def _oidc_logout_endpoint(provider: IROIDCProvider):
    async def endpoint(request: Request) -> RedirectResponse:
        post_logout = os.environ.get("FRONTEND_URL") or str(request.base_url).rstrip("/")
        return RedirectResponse(url=await oidc.build_logout_redirect(provider, post_logout))

    return endpoint


def _oidc_callback_endpoint(
    provider: IROIDCProvider,
    binding: IRProviderBinding,
    collection: RuntimeCollectionDescriptor,
    registry: RepositoryRegistry,
    callback_path: str,
    collections: dict[str, RuntimeCollectionDescriptor] | None = None,
):
    async def endpoint(request: Request, code: str) -> RedirectResponse:
        repo = registry.for_collection(collection.name)
        callback_url = str(request.base_url).rstrip("/") + callback_path
        login_code = await oidc.handle_callback(
            provider, binding, collection, repo, code, callback_url,
            collections=collections, registry=registry,
        )
        frontend_url = os.environ.get("FRONTEND_URL") or str(request.base_url).rstrip("/")
        return RedirectResponse(url=f"{frontend_url}/auth/callback?code={login_code}")

    return endpoint


async def _exchange_endpoint(payload: dict[str, str]) -> dict[str, str]:
    code = payload.get("code")
    if not code:
        raise HTTPException(status_code=400, detail="Missing code")
    redeemed = login_codes.redeem(code)
    if redeemed is None:
        raise HTTPException(status_code=401, detail="Invalid or expired code")
    subject, identity_collection, _ = redeemed
    return {"token": create_jwt_token(subject, identity_collection)}


def _field_annotation(field_config: dict[str, Any]) -> Any:
    field_type = field_config.get("type")

    if field_type in {"string", "id", "ref"}:
        return str
    if field_type == "number":
        return float
    if field_type == "boolean":
        return bool
    if field_type == "datetime":
        return datetime
    if field_type == "enum":
        values = field_config.get("values")
        if isinstance(values, list) and values:
            return Literal[tuple(values)]
        return str
    if field_type == "array":
        item_config = field_config.get("items")
        if isinstance(item_config, dict):
            return list[_field_annotation(item_config)]
        return list[Any]
    if field_type == "object":
        return dict[str, Any]
    return Any


def _build_endpoint(
    pipeline: Pipeline,
    body_model: type[BaseModel] | None,
    route: RuntimeRouteDescriptor,
):
    has_id_param = "{id}" in route.path

    if body_model is None:
        if has_id_param:

            async def endpoint_no_body_with_id(request: Request, id: str) -> Any:
                return await _run_pipeline(
                    pipeline=pipeline,
                    request=request,
                    body=None,
                    url_params={"id": id},
                )

            return endpoint_no_body_with_id

        async def endpoint_no_body(request: Request) -> Any:
            return await _run_pipeline(
                pipeline=pipeline,
                request=request,
                body=None,
                url_params={},
            )

        return endpoint_no_body

    exclude_unset = route.operation == "update"

    if has_id_param:

        async def endpoint_with_body_and_id(
            request: Request,
            id: str,
            payload: BaseModel,
        ) -> Any:
            return await _run_pipeline(
                pipeline=pipeline,
                request=request,
                body=payload.model_dump(mode="json", exclude_unset=exclude_unset),
                url_params={"id": id},
            )

        endpoint_with_body_and_id.__annotations__["payload"] = body_model
        return endpoint_with_body_and_id

    async def endpoint_with_body(request: Request, payload: BaseModel) -> Any:
        return await _run_pipeline(
            pipeline=pipeline,
            request=request,
            body=payload.model_dump(mode="json", exclude_unset=exclude_unset),
            url_params={},
        )

    endpoint_with_body.__annotations__["payload"] = body_model
    return endpoint_with_body


async def _run_pipeline(
    pipeline: Pipeline,
    request: Request,
    body: dict[str, Any] | None,
    url_params: dict[str, str],
) -> Any:
    try:
        path_params = {key: str(value) for key, value in request.path_params.items()}
        path_params.update(url_params)
        query_params = getattr(request, "query_params", None)
        query: dict[str, str | list[str]] = (
            {
                key: values if len(values) > 1 else values[0]
                for key in query_params
                for values in (query_params.getlist(key),)
            }
            if query_params is not None
            else {}
        )
        pre_resolved_principal: dict[str, Any] | None = getattr(request.state, "principal", None)
        ctx = await pipeline.run(
            headers=dict(request.headers),
            url_params=path_params,
            body=body,
            principal=pre_resolved_principal,
            query=query,
            cookies=dict(getattr(request, "cookies", {})),
        )
    except UnauthorizedError as error:
        raise HTTPException(status_code=401, detail=str(error)) from error
    except ForbiddenError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error
    except NotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return jsonable_encoder(ctx.response)


def _identity_methods(auth: RuntimeAuthConfig) -> set[str]:
    methods: set[str] = set()
    for identity in auth.identity_collections.values():
        methods.update(b.provider for b in identity.bindings)
    return methods


def _security_requirements(
    route: RuntimeRouteDescriptor, auth: RuntimeAuthConfig
) -> list[dict[str, list[str]]]:
    if route.is_public:
        return []

    methods = _identity_methods(auth)
    requirements: list[dict[str, list[str]]] = []
    if "apiKey" in methods:
        requirements.append({"ApiKeyAuth": []})
        requirements.append({"BearerAuth": []})
    if "password" in methods:
        requirements.append({"BasicAuth": []})
        requirements.append({"BearerAuth": []})
    return requirements


def _openapi_security_schemes(auth: RuntimeAuthConfig) -> dict[str, Any]:
    methods = _identity_methods(auth)
    schemes: dict[str, Any] = {}
    if "apiKey" in methods:
        schemes["ApiKeyAuth"] = {"type": "apiKey", "in": "header", "name": "X-API-Key"}
        schemes["BearerAuth"] = {"type": "http", "scheme": "bearer"}
    if "password" in methods:
        schemes["BasicAuth"] = {"type": "http", "scheme": "basic"}
        schemes["BearerAuth"] = {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "JWT",
        }
    return schemes


def _configure_openapi_security(app: FastAPI, auth: RuntimeAuthConfig) -> None:
    security_schemes = _openapi_security_schemes(auth)
    if not security_schemes:
        return

    def custom_openapi() -> dict[str, Any]:
        if app.openapi_schema:
            return app.openapi_schema

        openapi_schema = get_openapi(
            title=app.title,
            version=app.version,
            description=app.description,
            routes=app.routes,
        )
        components = openapi_schema.setdefault("components", {})
        schemes = components.setdefault("securitySchemes", {})
        schemes.update(security_schemes)
        app.openapi_schema = openapi_schema
        return app.openapi_schema

    app.openapi = custom_openapi
