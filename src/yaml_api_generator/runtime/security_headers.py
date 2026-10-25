"""Standard security response headers shared by runtime and generated backends.

A header the application already set is left untouched, so a route can still
choose its own framing or referrer policy.
"""

from typing import Any

STANDARD_HEADERS: tuple[tuple[str, str], ...] = (
    ("x-content-type-options", "nosniff"),
    ("x-frame-options", "DENY"),
    ("referrer-policy", "no-referrer"),
    ("strict-transport-security", "max-age=31536000; includeSubDomains"),
    ("cross-origin-opener-policy", "same-origin"),
)


class SecurityHeadersMiddleware:
    """ASGI middleware adding STANDARD_HEADERS to every HTTP response."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message: dict[str, Any]) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                present = {bytes(name).lower() for name, _ in headers}
                headers.extend(
                    (name.encode("latin-1"), value.encode("latin-1"))
                    for name, value in STANDARD_HEADERS
                    if name.encode("latin-1") not in present
                )
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_with_headers)


class DjangoSecurityHeadersMiddleware:
    """Django middleware adding STANDARD_HEADERS to every response."""

    def __init__(self, get_response: Any) -> None:
        self.get_response = get_response

    def __call__(self, request: Any) -> Any:
        response = self.get_response(request)
        for name, value in STANDARD_HEADERS:
            response.headers.setdefault(name, value)
        return response
