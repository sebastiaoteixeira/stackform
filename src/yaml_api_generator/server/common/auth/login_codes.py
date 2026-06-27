"""One-time login codes for the dev server's SSO callback.

The generated backend persists codes in the identity datastore so they survive
across worker processes. The dev server is single-process, so an in-memory store
with the same single-use, TTL-bounded semantics is enough.
"""

import secrets
import time

_TTL_SECONDS = 60


class LoginCodeStore:
    def __init__(self) -> None:
        self._codes: dict[str, tuple[str, str, float]] = {}

    def issue(self, subject: str, identity_collection: str) -> str:
        code = secrets.token_urlsafe(32)
        self._codes[code] = (subject, identity_collection, time.time() + _TTL_SECONDS)
        return code

    def redeem(self, code: str) -> tuple[str | None, str | None, None] | None:
        entry = self._codes.pop(code, None)
        if entry is None:
            return None
        subject, identity_collection, expires_at = entry
        if expires_at < time.time():
            return None
        return subject, identity_collection, None


login_codes = LoginCodeStore()
