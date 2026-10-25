"""ASGI middleware the spec's api block enables, shared by both dev servers."""

from functools import reduce

from starlette import types
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware

from yaml_api_generator.ir import IRApi
from yaml_api_generator.runtime.security_headers import SecurityHeadersMiddleware


def api_middleware(api: IRApi) -> tuple[Middleware, ...]:
    """Return the enabled middleware, outermost first."""
    return (
        *((Middleware(SecurityHeadersMiddleware),) if api.security_headers else ()),
        *(
            (Middleware(
                CORSMiddleware,
                allow_origins=api.cors.origins,
                allow_methods=api.cors.methods,
                allow_headers=api.cors.headers,
                allow_credentials=api.cors.credentials,
            ),)
            if api.cors else ()
        ),
    )


def wrap_asgi(app: types.ASGIApp, middleware: tuple[Middleware, ...]) -> types.ASGIApp:
    """Wrap a bare ASGI app so the first middleware ends up outermost."""
    return reduce(
        lambda inner, layer: layer.cls(inner, *layer.args, **layer.kwargs),
        reversed(middleware),
        app,
    )
