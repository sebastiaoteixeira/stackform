"""SAML 2.0 service provider: login redirect, assertion consumer, metadata and single logout."""

import time
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx
from onelogin.saml2.auth import OneLogin_Saml2_Auth
from onelogin.saml2.idp_metadata_parser import OneLogin_Saml2_IdPMetadataParser
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import Response, RedirectResponse

_POST_BINDING = "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST"
_REDIRECT_BINDING = "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect"
_EMAIL_NAME_ID = "urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress"
_SLO_MESSAGES = frozenset({"SAMLRequest", "SAMLResponse"})
_REPLAY_WINDOW_SECONDS = 300
_REQUEST_COOKIE = "saml_request_id"


def assertion_claims(attributes: dict[str, list[Any]], name_id: str | None) -> dict[str, Any]:
    """Flatten an assertion into claims: single-valued attributes become scalars, NameID becomes ``sub``."""
    return {
        **{name: values[0] if len(values) == 1 else values for name, values in attributes.items() if values},
        "sub": name_id,
    }


class AssertionLedger(Protocol):
    """Remembers consumed assertion IDs until they expire."""

    async def consume(self, assertion_id: str, expires_at: float) -> bool:
        """Record ``assertion_id``; ``False`` when it was already consumed."""
        ...


@dataclass
class MemoryAssertionLedger:
    """An ``AssertionLedger`` held by one process."""

    _expiries: dict[str, float] = field(default_factory=dict)

    async def consume(self, assertion_id: str, expires_at: float) -> bool:
        now = time.time()
        self._expiries = {seen: expiry for seen, expiry in self._expiries.items() if expiry >= now}
        if assertion_id in self._expiries:
            return False
        self._expiries[assertion_id] = expires_at
        return True


@dataclass
class SAMLServiceProvider:
    """The SP endpoints mounted under ``login_path``, trusting the IdP published at ``idp_metadata_url``."""

    idp_metadata_url: str
    entity_id: str
    login_path: str
    assertions: AssertionLedger = field(default_factory=MemoryAssertionLedger)
    _idp: dict[str, Any] | None = field(default=None, init=False, repr=False)

    @property
    def callback_path(self) -> str:
        return f"{self.login_path}/callback"

    @property
    def logout_path(self) -> str:
        return f"{self.login_path}/logout"

    async def login(self, request: Request) -> RedirectResponse:
        """Redirect to the IdP, remembering the AuthnRequest so only its response is consumed."""
        auth = await self._auth(request)
        response = RedirectResponse(url=auth.login())
        https = request.url.scheme == "https"
        response.set_cookie(
            _REQUEST_COOKIE,
            auth.get_last_request_id(),
            max_age=_REPLAY_WINDOW_SECONDS,
            path=self.callback_path,
            httponly=True,
            secure=https,
            # The IdP POSTs the response cross-site, which only a SameSite=None cookie survives
            samesite="none" if https else "lax",
        )
        return response

    def forget_request(self, response: Response) -> None:
        response.delete_cookie(_REQUEST_COOKIE, path=self.callback_path)

    async def claims(self, request: Request) -> dict[str, Any]:
        """The claims of the response the IdP POSTs to the callback, in answer to this browser's AuthnRequest."""
        auth = await self._auth(request)
        if "SAMLResponse" not in (await request.form()):
            raise HTTPException(status_code=400, detail="Missing SAMLResponse")
        request_id = request.cookies.get(_REQUEST_COOKIE)
        try:
            auth.process_response(request_id=request_id)
        except (ValueError, SyntaxError) as error:
            raise HTTPException(status_code=400, detail="Malformed SAMLResponse") from error
        if auth.get_errors() or not auth.is_authenticated():
            raise HTTPException(
                status_code=401,
                detail=f"SAML authentication failed: {auth.get_last_error_reason() or 'not authenticated'}",
            )
        if request_id is None or auth.get_last_response_in_response_to() != request_id:
            raise HTTPException(status_code=401, detail="SAML response answers no pending login")
        expires_at = auth.get_last_assertion_not_on_or_after() or time.time() + _REPLAY_WINDOW_SECONDS
        if not await self.assertions.consume(auth.get_last_assertion_id(), expires_at):
            raise HTTPException(status_code=401, detail="SAML assertion already consumed")
        return assertion_claims(auth.get_attributes(), auth.get_nameid())

    async def metadata(self, request: Request) -> str:
        return (await self._auth(request)).get_settings().get_sp_metadata()

    async def logout_redirect(self, request: Request, return_to: str) -> str:
        """Start SP-initiated logout, or answer the IdP's logout message arriving at the SLS endpoint."""
        auth = await self._auth(request)
        if _SLO_MESSAGES & request.query_params.keys():
            redirect = auth.process_slo(keep_local_session=True)
            if auth.get_errors():
                raise HTTPException(status_code=400, detail=f"SAML logout failed: {auth.get_last_error_reason()}")
            return redirect or return_to
        if auth.get_slo_url() is None:
            raise HTTPException(status_code=501, detail="Provider does not support single logout")
        return auth.logout(return_to=return_to)

    async def _idp_settings(self) -> dict[str, Any]:
        if self._idp is None:
            async with httpx.AsyncClient() as client:
                response = await client.get(self.idp_metadata_url)
                response.raise_for_status()
            self._idp = OneLogin_Saml2_IdPMetadataParser.parse(response.text)
        return self._idp

    async def _auth(self, request: Request) -> OneLogin_Saml2_Auth:
        base = str(request.base_url).rstrip("/")
        form = await request.form() if request.method == "POST" else {}
        request_data = {
            "https": "on" if request.url.scheme == "https" else "off",
            "http_host": request.url.netloc,
            "script_name": request.url.path,
            "get_data": dict(request.query_params),
            "post_data": dict(form),
        }
        settings = {
            **await self._idp_settings(),
            "strict": True,
            "sp": {
                "entityId": self.entity_id,
                "assertionConsumerService": {"url": base + self.callback_path, "binding": _POST_BINDING},
                "singleLogoutService": {"url": base + self.logout_path, "binding": _REDIRECT_BINDING},
                "NameIDFormat": _EMAIL_NAME_ID,
            },
            "security": {"requestedAuthnContext": False},
        }
        return OneLogin_Saml2_Auth(request_data, settings)
