"""FastAPI server builder."""

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from ..common.context_builder import build_runtime_context
from ..common.loader import create_repositories, ensure_spec_dir_importable, initialize_indexes
from ..common.server_context import RuntimeContext
from ..common.repositories import RepositoryRegistry
from ..common.vendored_packages import install_vendored_packages
from .factory import register_fastapi_routes


def _has_idp_providers(ctx: RuntimeContext) -> bool:
    from yaml_api_generator.ir.api import IROIDCProvider
    return any(
        isinstance(p, IROIDCProvider) and p.is_idp
        for p in ctx.auth.providers.values()
    )


def _idp_provisioning_middleware(ctx: RuntimeContext, registry: RepositoryRegistry) -> type[BaseHTTPMiddleware]:
    identity_collections = ctx.auth.identity_collections
    identity_id_fields = ctx.auth.identity_id_fields
    providers = ctx.auth.providers
    collections = ctx.collections

    class IdpProvisioningMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next: Any) -> Response:
            from ..common.auth.utils import extract_bearer_token
            from ..common.steps.authentication import _resolve_idp_principal
            from ..common.steps.authorization import UnauthorizedError
            bearer_token = extract_bearer_token(dict(request.headers))
            if bearer_token is not None:
                try:
                    principal = await _resolve_idp_principal(
                        bearer_token,
                        identity_collections,
                        collections,
                        providers,
                        registry,
                    )
                    if principal is not None:
                        request.state.principal = principal
                except UnauthorizedError as exc:
                    from starlette.responses import JSONResponse
                    return JSONResponse(status_code=401, content={"detail": str(exc)})
            return await call_next(request)

    return IdpProvisioningMiddleware


def build_app(yaml_file: str, schema_file: str | Path | None = None) -> FastAPI:
    """Build FastAPI application from YAML specification.

    Args:
        yaml_file: Path to YAML API specification
        schema_file: Optional path to JSON schema for validation

    Returns:
        Configured FastAPI application with routes and middleware
    """
    ensure_spec_dir_importable(yaml_file)
    ir, registry = create_repositories(yaml_file, schema_file)
    install_vendored_packages(ir.vendored_imports)
    ctx = build_runtime_context(ir)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        await initialize_indexes(ir, registry)
        yield

    app = FastAPI(lifespan=lifespan)

    if ir.api.cors:
        from fastapi.middleware.cors import CORSMiddleware
        app.add_middleware(
            CORSMiddleware,
            allow_origins=ir.api.cors.origins,
            allow_methods=ir.api.cors.methods,
            allow_headers=ir.api.cors.headers,
            allow_credentials=ir.api.cors.credentials,
        )

    if _has_idp_providers(ctx):
        app.add_middleware(_idp_provisioning_middleware(ctx, registry))

    register_fastapi_routes(app, ctx, registry)

    return app
