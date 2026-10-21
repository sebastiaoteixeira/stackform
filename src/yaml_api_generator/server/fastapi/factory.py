import os
import re
import secrets
from collections.abc import Callable, Mapping
from typing import Annotated, Any, Literal

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.encoders import jsonable_encoder
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse, RedirectResponse, StreamingResponse
from pydantic import BaseModel, Field, create_model

from yaml_api_generator.runtime.dpop import DPoPProofFactory
from yaml_api_generator.runtime.payloads import (
    CONSTRAINTS,
    SCALAR_TYPES,
    STRICT_TYPES,
    Payload,
    partial,
)
from yaml_api_generator.runtime.files import FileError, RecordFiles
from yaml_api_generator.runtime.file_requests import (
    json_request_body,
    read_json,
    read_upload,
    upload_request_body,
)
from yaml_api_generator.runtime.multipart import file_download_responses, file_upload_body
from yaml_api_generator.ir import writable_fields
from yaml_api_generator.ir.api import IRDto, IROIDCProvider, IRProviderBinding
from yaml_api_generator.utils.strings import to_pascal_case, to_py_identifier
from ..common.auth import oidc
from ..common.auth.login_codes import login_codes
from ..common.auth.session_tokens import SessionTokens
from ..common.server_context import (
    RuntimeAuthConfig,
    RuntimeCollectionDescriptor,
    RuntimeContext,
    RuntimeFileRouteDescriptor,
    RuntimeIdentityDescriptor,
    RuntimeRouteDescriptor,
)
from ..common.pipeline import Pipeline
from ..common.pipeline_builder import PipelineBuilder
from ..common.repositories import BaseRepository, RepositoryRegistry
from ..common.request_body import RecordBody, RequestBody
from ..common.request_context import RequestContext
from ..common.steps import ConflictError, ForbiddenError, NotFoundError, UnauthorizedError
from ..common.steps.validation import credential_properties, login_properties
from .session_cookie import clear_session_cookies, issue_csrf_token, set_session_cookies


WRITE_OPERATIONS = frozenset({"create", "update", "replace"})
_PATH_TOKEN = re.compile(r"\{(\w+)\}")

BodyReader = Callable[[Request], RequestBody | None]

# Per write operation of a file entity: how its body is read and documented
_UPLOAD_BODIES = {
    "create": (read_upload, upload_request_body),
    "update": (read_upload, upload_request_body),
    "replace": (read_json, json_request_body),
}


def _model_field(config: dict[str, Any]) -> tuple[Any, Any]:
    annotation = _field_annotation(config)
    constraints = {CONSTRAINTS[key]: config[key] for key in CONSTRAINTS if key in config}
    if config.get("required"):
        return annotation, Field(config.get("default", ...), **constraints)
    return annotation | None, Field(config.get("default"), **constraints)


def create_pydantic_model_fields(
    properties: dict[str, dict[str, Any]],
) -> dict[str, tuple[Any, Any]]:
    return {name: _model_field(config) for name, config in properties.items()}


def create_pydantic_model(
    collection: RuntimeCollectionDescriptor,
    operation: str,
    identity_collection: RuntimeIdentityDescriptor | None = None,
    dto: IRDto | None = None,
) -> type[BaseModel] | None:
    """The body model of ``operation``; nested objects and formats are left to ``ValidateBodyStep``."""
    model_name = to_pascal_case(collection.name)
    if operation == "login" and identity_collection is not None:
        return create_model(
            f"{model_name}LoginPayload",
            __base__=Payload,
            **create_pydantic_model_fields(login_properties(identity_collection)),
        )
    if operation == "refresh":
        return create_model(
            f"{model_name}RefreshPayload",
            __base__=Payload,
            refresh_token=(str, Field(..., min_length=1)),
        )
    if operation not in WRITE_OPERATIONS:
        return None
    if dto is not None:
        return create_model(
            to_pascal_case(dto.name),
            __base__=Payload,
            **create_pydantic_model_fields(writable_fields(dto.fields)),
        )
    fields = create_model(
        f"{model_name}Fields",
        __base__=Payload,
        **create_pydantic_model_fields(writable_fields(collection.fields, collection.files)),
    )
    if operation == "update":
        return partial(fields, f"{model_name}UpdatePayload")
    return create_model(
        f"{model_name}{operation.capitalize()}Payload",
        __base__=fields,
        **create_pydantic_model_fields(credential_properties(operation, identity_collection)),
    )


def register_fastapi_routes(
    app: FastAPI,
    ctx: RuntimeContext,
    registry: RepositoryRegistry,
    files: Mapping[str, RecordFiles] | None = None,
) -> dict[tuple[str, str], Pipeline]:
    files = files or {}
    pipelines: dict[tuple[str, str], Pipeline] = {}
    pipeline_builder = PipelineBuilder(ctx=ctx, registry=registry, files=files)

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
                route.body_dto,
            )
            if ctx.session.uses_cookie and route.operation == "refresh":
                body_model = None

        record_files = files.get(route.collection)
        if (
            record_files is not None
            and body_model is not None
            and route.handler is None
            and route.operation in _UPLOAD_BODIES
        ):
            _add_upload_route(app, ctx, pipeline, route, body_model, record_files)
            continue

        endpoint = _build_endpoint(
            pipeline, body_model, route, uses_cookie=ctx.session.uses_cookie
        )
        app.add_api_route(
            route.path,
            endpoint,
            methods=[route.method],
            openapi_extra=_openapi_extra(route, ctx.auth),
        )

    for file_route in ctx.file_routes:
        pipeline = pipeline_builder.build_for_file_route(file_route)
        pipelines[(file_route.method, file_route.path)] = pipeline
        _FILE_ROUTES[file_route.action](
            app, ctx, pipeline, file_route, files[file_route.collection]
        )

    register_provider_routes(app, ctx, registry, pipeline_builder.tokens)
    if ctx.session.uses_cookie:
        app.add_api_route(
            f"{_base_prefix(ctx)}/auth/logout",
            _logout_endpoint(),
            methods=["POST"],
            status_code=204,
        )
    _configure_openapi_security(app, ctx.auth)

    return pipelines


def _openapi_extra(
    route: RuntimeRouteDescriptor, auth: RuntimeAuthConfig, **extra: Any
) -> dict[str, Any] | None:
    security = _security_requirements(route, auth)
    return ({"security": security} if security else {}) | extra or None


def _path_parameters(path: str) -> list[dict[str, Any]]:
    return [
        {"name": token, "in": "path", "required": True, "schema": {"type": "string"}}
        for token in _PATH_TOKEN.findall(path)
    ]


def _add_upload_route(
    app: FastAPI,
    ctx: RuntimeContext,
    pipeline: Pipeline,
    route: RuntimeRouteDescriptor,
    body_model: type[BaseModel],
    record_files: RecordFiles,
) -> None:
    partial = route.operation == "update"
    read, document = _UPLOAD_BODIES[route.operation]
    app.add_api_route(
        route.path,
        _record_endpoint(
            pipeline,
            route.operation,
            lambda request: RecordBody(request, body_model, partial, read),
            uses_cookie=ctx.session.uses_cookie,
        ),
        methods=[route.method],
        openapi_extra=_openapi_extra(
            route,
            ctx.auth,
            requestBody=document(record_files, body_model, partial=partial),
            parameters=_path_parameters(route.path),
        ),
    )


def _add_download_route(
    app: FastAPI,
    ctx: RuntimeContext,
    pipeline: Pipeline,
    route: RuntimeFileRouteDescriptor,
    _: RecordFiles,
) -> None:
    app.add_api_route(
        route.path,
        _download_endpoint(pipeline, uses_cookie=ctx.session.uses_cookie),
        methods=[route.method],
        responses=file_download_responses(),
        openapi_extra=_openapi_extra(
            route.source, ctx.auth, parameters=_path_parameters(route.path)
        ),
    )


def _add_replace_route(
    app: FastAPI,
    ctx: RuntimeContext,
    pipeline: Pipeline,
    route: RuntimeFileRouteDescriptor,
    record_files: RecordFiles,
) -> None:
    app.add_api_route(
        route.path,
        _record_endpoint(
            pipeline,
            route.source.operation,
            RequestBody,
            uses_cookie=ctx.session.uses_cookie,
        ),
        methods=[route.method],
        openapi_extra=_openapi_extra(
            route.source,
            ctx.auth,
            requestBody=file_upload_body(record_files.fields[route.field], item=route.item),
            parameters=_path_parameters(route.path),
        ),
    )


def _add_remove_route(
    app: FastAPI,
    ctx: RuntimeContext,
    pipeline: Pipeline,
    route: RuntimeFileRouteDescriptor,
    _: RecordFiles,
) -> None:
    app.add_api_route(
        route.path,
        _record_endpoint(
            pipeline,
            route.source.operation,
            lambda _request: None,
            uses_cookie=ctx.session.uses_cookie,
        ),
        methods=[route.method],
        openapi_extra=_openapi_extra(
            route.source, ctx.auth, parameters=_path_parameters(route.path)
        ),
    )


_FILE_ROUTES = {
    "download": _add_download_route,
    "replace": _add_replace_route,
    "remove": _add_remove_route,
}


def _record_endpoint(
    pipeline: Pipeline, operation: str, read: BodyReader, *, uses_cookie: bool
):
    async def endpoint(request: Request) -> Any:
        return await _run_pipeline(
            pipeline=pipeline,
            request=request,
            body=None,
            url_params={},
            uses_cookie=uses_cookie,
            operation=operation,
            upload=read(request),
        )

    return endpoint


def _download_endpoint(pipeline: Pipeline, *, uses_cookie: bool):
    async def endpoint(request: Request) -> StreamingResponse:
        ctx = await _execute(
            pipeline=pipeline,
            request=request,
            body=None,
            url_params={},
            uses_cookie=uses_cookie,
        )
        return StreamingResponse(ctx.response.chunks, headers=ctx.response.headers)

    return endpoint


def _base_prefix(ctx: RuntimeContext) -> str:
    prefix = ctx.app.base_path
    if ctx.app.api_version:
        prefix = f"{prefix}/{ctx.app.api_version}"
    return prefix


def register_provider_routes(
    app: FastAPI,
    ctx: RuntimeContext,
    registry: RepositoryRegistry,
    session_tokens: SessionTokens,
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
            dpop = _load_dpop_factory(provider) if provider.dpop else None
            app.add_api_route(
                login_path,
                _oidc_login_endpoint(provider, callback_path, name),
                methods=["GET"],
            )
            app.add_api_route(
                callback_path,
                _oidc_callback_endpoint(
                    provider,
                    binding,
                    collection,
                    registry,
                    callback_path,
                    collections=ctx.collections,
                    dpop=dpop,
                ),
                methods=["GET"],
            )

    if has_oidc:
        app.add_api_route(
            f"{base_prefix}/auth/exchange",
            _exchange_endpoint(session_tokens, uses_cookie=ctx.session.uses_cookie),
            methods=["POST"],
        )


def _providers_listing_endpoint(listing: list[dict[str, str]]):
    async def endpoint() -> list[dict[str, str]]:
        return listing

    return endpoint


def _oidc_cookie_name(collection: str, provider: str, purpose: str) -> str:
    return f"{to_py_identifier(collection)}_{to_py_identifier(provider)}_{purpose}"


def _load_dpop_factory(provider: IROIDCProvider) -> DPoPProofFactory:
    env_name = f"{to_py_identifier(provider.name).upper()}_DPOP_PRIVATE_KEY"
    private_key = os.environ.get(env_name)
    if private_key is None:
        raise RuntimeError(
            f"Provider '{provider.name}' enables DPoP but {env_name} is not set"
        )
    try:
        return DPoPProofFactory.from_pem(private_key.replace("\\n", "\n"))
    except (TypeError, ValueError) as error:
        raise RuntimeError(f"{env_name} is not a valid EC P-256 private key") from error


def _oidc_login_endpoint(
    provider: IROIDCProvider,
    callback_path: str,
    collection_name: str,
):
    async def endpoint(request: Request) -> RedirectResponse:
        callback_url = str(request.base_url).rstrip("/") + callback_path
        state = secrets.token_urlsafe(32)
        verifier = oidc.create_pkce_verifier() if provider.pkce else None
        challenge = oidc.pkce_challenge(verifier) if verifier is not None else None
        url = await oidc.build_login_redirect(
            provider,
            callback_url,
            state=state,
            code_challenge=challenge,
        )
        response = RedirectResponse(url=url)
        cookie_options = {
            "max_age": 300,
            "httponly": True,
            "secure": request.url.scheme == "https",
            "samesite": "lax",
            "path": callback_path,
        }
        response.set_cookie(
            _oidc_cookie_name(collection_name, provider.name, "state"),
            state,
            **cookie_options,
        )
        if verifier is not None:
            response.set_cookie(
                _oidc_cookie_name(collection_name, provider.name, "pkce_verifier"),
                verifier,
                **cookie_options,
            )
        return response

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
    dpop: DPoPProofFactory | None = None,
):
    async def endpoint(
        request: Request,
        code: str,
        state: str | None = None,
    ) -> RedirectResponse:
        state_cookie = _oidc_cookie_name(collection.name, provider.name, "state")
        expected_state = request.cookies.get(state_cookie)
        if (
            not state
            or not expected_state
            or not secrets.compare_digest(state, expected_state)
        ):
            raise HTTPException(status_code=400, detail="Invalid OIDC state")
        verifier_cookie = _oidc_cookie_name(
            collection.name, provider.name, "pkce_verifier"
        )
        verifier = request.cookies.get(verifier_cookie) if provider.pkce else None
        if provider.pkce and not verifier:
            raise HTTPException(status_code=400, detail="Missing PKCE verifier")
        repo = registry.for_collection(collection.name)
        callback_url = str(request.base_url).rstrip("/") + callback_path
        login_code = await oidc.handle_callback(
            provider, binding, collection, repo, code, callback_url,
            collections=collections, registry=registry,
            code_verifier=verifier,
            dpop=dpop,
        )
        frontend_url = os.environ.get("FRONTEND_URL") or str(request.base_url).rstrip("/")
        response = RedirectResponse(
            url=f"{frontend_url}/auth/callback?code={login_code}"
        )
        response.delete_cookie(state_cookie, path=callback_path)
        if provider.pkce:
            response.delete_cookie(verifier_cookie, path=callback_path)
        return response

    return endpoint


def _exchange_endpoint(session_tokens: SessionTokens, *, uses_cookie: bool = False):
    async def endpoint(request: Request, payload: dict[str, str]) -> Any:
        code = payload.get("code")
        if not code:
            raise HTTPException(status_code=400, detail="Missing code")
        redeemed = login_codes.redeem(code)
        if redeemed is None:
            raise HTTPException(status_code=401, detail="Invalid or expired code")
        subject, identity_collection, _ = redeemed
        session = session_tokens.issue(subject, identity_collection)
        if not uses_cookie:
            return session
        csrf_token = issue_csrf_token()
        response = JSONResponse({"csrf_token": csrf_token})
        set_session_cookies(
            response,
            request,
            session["token"],
            csrf_token,
            session.get("refresh_token"),
        )
        return response

    return endpoint


def _logout_endpoint():
    async def endpoint() -> Response:
        response = Response(status_code=204)
        clear_session_cookies(response)
        return response

    return endpoint


def _field_annotation(config: dict[str, Any]) -> Any:
    kind = config.get("type", "string")
    if kind == "enum":
        return Literal[tuple(config["values"])]
    if kind == "array":
        return list[_field_annotation(config["items"])] if "items" in config else list[Any]
    if kind == "object":
        return dict[str, Any]
    scalar = SCALAR_TYPES[kind]
    return Annotated[scalar, Field(strict=True)] if scalar in STRICT_TYPES else scalar


def _build_endpoint(
    pipeline: Pipeline,
    body_model: type[BaseModel] | None,
    route: RuntimeRouteDescriptor,
    *,
    uses_cookie: bool = False,
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
                    uses_cookie=uses_cookie,
                    operation=route.operation,
                )

            return endpoint_no_body_with_id

        async def endpoint_no_body(request: Request) -> Any:
            return await _run_pipeline(
                pipeline=pipeline,
                request=request,
                body=None,
                url_params={},
                uses_cookie=uses_cookie,
                operation=route.operation,
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
                uses_cookie=uses_cookie,
                operation=route.operation,
            )

        endpoint_with_body_and_id.__annotations__["payload"] = body_model
        return endpoint_with_body_and_id

    async def endpoint_with_body(request: Request, payload: BaseModel) -> Any:
        return await _run_pipeline(
            pipeline=pipeline,
            request=request,
            body=payload.model_dump(mode="json", exclude_unset=exclude_unset),
            url_params={},
            uses_cookie=uses_cookie,
            operation=route.operation,
        )

    endpoint_with_body.__annotations__["payload"] = body_model
    return endpoint_with_body


async def _execute(
    pipeline: Pipeline,
    request: Request,
    body: dict[str, Any] | None,
    url_params: dict[str, str],
    uses_cookie: bool = False,
    operation: str | None = None,
    upload: RequestBody | None = None,
) -> RequestContext:
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
        headers = dict(request.headers)
        if uses_cookie and "authorization" not in headers:
            session_token = request.cookies.get("session")
            if session_token:
                headers["authorization"] = f"Bearer {session_token}"
        if uses_cookie and operation == "refresh":
            body = {"refresh_token": request.cookies.get("refresh_token")}
        ctx = await pipeline.run(
            headers=headers,
            url_params=path_params,
            body=body,
            principal=pre_resolved_principal,
            query=query,
            cookies=dict(getattr(request, "cookies", {})),
            upload=upload,
        )
    except UnauthorizedError as error:
        raise HTTPException(status_code=401, detail=str(error)) from error
    except ForbiddenError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error
    except NotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ConflictError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except FileError as error:
        raise HTTPException(status_code=error.status_code, detail=str(error)) from error
    return ctx


async def _run_pipeline(
    pipeline: Pipeline,
    request: Request,
    body: dict[str, Any] | None,
    url_params: dict[str, str],
    uses_cookie: bool = False,
    operation: str | None = None,
    upload: RequestBody | None = None,
) -> Any:
    ctx = await _execute(pipeline, request, body, url_params, uses_cookie, operation, upload)
    response_payload = jsonable_encoder(ctx.response)
    if not uses_cookie or operation not in {"login", "refresh"}:
        return response_payload
    if not isinstance(response_payload, dict) or "token" not in response_payload:
        return response_payload
    csrf_token = issue_csrf_token()
    content = {
        key: value
        for key, value in response_payload.items()
        if key not in {"token", "refresh_token"}
    }
    content["csrf_token"] = csrf_token
    response = JSONResponse(content)
    set_session_cookies(
        response,
        request,
        response_payload["token"],
        csrf_token,
        response_payload.get("refresh_token"),
    )
    return response


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
