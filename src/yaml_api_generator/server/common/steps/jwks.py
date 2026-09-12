from ..auth.jwt import SessionTokens
from ..request_context import RequestContext
from . import Step


def JWKSStep(tokens: SessionTokens) -> Step:
    async def step(ctx: RequestContext) -> RequestContext:
        ctx.response = tokens.public_jwks()
        return ctx

    return step
