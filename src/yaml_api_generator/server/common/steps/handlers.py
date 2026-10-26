"""Call a user handler through the contract shared with every generated backend."""

from yaml_api_generator.runtime.handler_requests import HandlerRequest, invoke

from ..request_context import RequestContext
from . import Step


def HandlerStep(handler: str) -> Step:
    async def step(ctx: RequestContext) -> RequestContext:
        ctx.response = await invoke(handler, handler_request(ctx))
        return ctx

    return step


def handler_request(ctx: RequestContext) -> HandlerRequest:
    return HandlerRequest(
        params=dict(ctx.url_params),
        query=dict(ctx.query or {}),
        headers=dict(ctx.headers),
        cookies=dict(ctx.cookies or {}),
        body=ctx.body,
        principal=ctx.principal,
        inputs=dict(ctx.service_inputs or {}),
    )
