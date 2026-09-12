from ..auth.session_tokens import SessionTokens
from ..request_context import RequestContext
from . import Step
from .authorization import UnauthorizedError


def RefreshStep(session_tokens: SessionTokens) -> Step:
    async def step(ctx: RequestContext) -> RequestContext:
        body = ctx.body if isinstance(ctx.body, dict) else {}
        refresh_token = body.get("refresh_token")
        rotated = (
            session_tokens.rotate(refresh_token)
            if isinstance(refresh_token, str)
            else None
        )
        if rotated is None:
            raise UnauthorizedError("Invalid refresh token")

        ctx.response = rotated
        return ctx

    return step
