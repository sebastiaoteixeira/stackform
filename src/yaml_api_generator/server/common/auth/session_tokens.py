"""Access-token issuance and refresh-token rotation for the dev server.

The generated backend persists refresh records in the identity datastore so they
survive across worker processes. The dev server is single-process, so an
in-memory store with the same single-use, family-revocation semantics is enough.
"""

from dataclasses import dataclass
from uuid import uuid4

from yaml_api_generator.ir.api import IRSession

from .jwt import create_jwt_token, create_refresh_token, decode_refresh_token

REFRESH_TTL_SECONDS = 30 * 24 * 3600


@dataclass
class _RefreshRecord:
    sub: str
    identity_collection: str
    sid: str
    used: bool = False
    revoked: bool = False


class SessionTokens:
    """Mints the session payload a login returns, honouring the spec's session block."""

    def __init__(self, session: IRSession) -> None:
        self._session = session
        self._records: dict[str, _RefreshRecord] = {}

    @property
    def rotates(self) -> bool:
        return self._session.refresh

    def issue(
        self, sub: str, identity_collection: str, sid: str | None = None
    ) -> dict[str, str]:
        token = create_jwt_token(sub, identity_collection, self._session.ttl)
        if not self._session.refresh:
            return {"token": token}

        jti = uuid4().hex
        record = _RefreshRecord(sub, identity_collection, sid or uuid4().hex)
        self._records[jti] = record
        return {
            "token": token,
            "refresh_token": create_refresh_token(
                sub, identity_collection, jti, record.sid, REFRESH_TTL_SECONDS
            ),
        }

    def revoke_session(self, sid: str) -> None:
        for record in self._records.values():
            if record.sid == sid:
                record.revoked = True

    def rotate(self, refresh_token: str) -> dict[str, str] | None:
        """Spend a refresh token, revoking its whole family when it was already spent."""
        claims = decode_refresh_token(refresh_token)
        if claims is None:
            return None

        record = self._records.get(claims["jti"])
        if record is None or record.used or record.revoked:
            self.revoke_session(claims["sid"])
            return None

        record.used = True
        return self.issue(record.sub, record.identity_collection, record.sid)
