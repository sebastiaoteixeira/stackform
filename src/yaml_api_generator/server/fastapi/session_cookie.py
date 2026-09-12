import secrets

from fastapi import Request, Response

SESSION_COOKIE = "session"
REFRESH_COOKIE = "refresh_token"
CSRF_COOKIE = "csrf_token"
CSRF_HEADER = "x-csrf-token"
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})


def issue_csrf_token() -> str:
    return secrets.token_urlsafe(32)


def csrf_valid(request: Request) -> bool:
    has_auth_cookie = any(
        name in request.cookies for name in (SESSION_COOKIE, REFRESH_COOKIE)
    )
    if request.method in SAFE_METHODS or not has_auth_cookie:
        return True
    cookie = request.cookies.get(CSRF_COOKIE)
    header = request.headers.get(CSRF_HEADER)
    return bool(cookie) and bool(header) and secrets.compare_digest(cookie, header)


def set_session_cookies(
    response: Response,
    request: Request,
    token: str,
    csrf_token: str,
    refresh_token: str | None = None,
) -> None:
    secure = request.url.scheme == "https"
    response.set_cookie(
        SESSION_COOKIE, token, httponly=True, secure=secure, samesite="lax", path="/"
    )
    response.set_cookie(
        CSRF_COOKIE, csrf_token, httponly=False, secure=secure, samesite="lax", path="/"
    )
    if refresh_token is not None:
        response.set_cookie(
            REFRESH_COOKIE,
            refresh_token,
            httponly=True,
            secure=secure,
            samesite="lax",
            path="/",
        )


def clear_session_cookies(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.delete_cookie(REFRESH_COOKIE, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")
