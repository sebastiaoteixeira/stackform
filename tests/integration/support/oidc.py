"""Live OIDC providers: an issuer of RS256 tokens behind discovery and JWKS, and an authorization server for app login."""

import json
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from urllib.parse import parse_qs, urlencode, urlparse

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

KEY_ID = "test-key"


class _IssuerHandler(BaseHTTPRequestHandler):
    def __init__(self, documents: dict[str, dict], *args) -> None:
        self.documents = documents
        super().__init__(*args)

    def do_GET(self) -> None:
        document = self.documents.get(self.path)
        if document is None:
            self.send_error(404)
            return
        body = json.dumps(document).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args) -> None:
        return


@dataclass(frozen=True)
class Issuer:
    url: str
    audience: str
    key: rsa.RSAPrivateKey

    @property
    def discovery_url(self) -> str:
        return f"{self.url}/.well-known/openid-configuration"

    def token(self, sub: str, **claims) -> str:
        now = int(time.time())
        payload = {"iss": self.url, "aud": self.audience, "sub": sub, "iat": now, "exp": now + 600, **claims}
        return jwt.encode(payload, self.key, algorithm="RS256", headers={"kid": KEY_ID})

    def bearer(self, sub: str, **claims) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token(sub, **claims)}"}


@contextmanager
def live_issuer(audience: str) -> Iterator[Issuer]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = {**json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key())), "kid": KEY_ID, "alg": "RS256", "use": "sig"}
    documents: dict[str, dict] = {"/jwks": {"keys": [jwk]}}
    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(_IssuerHandler, documents))
    host, port = server.server_address
    issuer = Issuer(f"http://{host}:{port}", audience, key)
    documents["/.well-known/openid-configuration"] = {"issuer": issuer.url, "jwks_uri": f"{issuer.url}/jwks"}
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield issuer
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


class _AuthorizationServerHandler(BaseHTTPRequestHandler):
    """Authorization-code flow for one confidential client: the token endpoint demands its secret."""

    def __init__(self, server: "AuthorizationServer", *args) -> None:
        self.authorization_server = server
        super().__init__(*args)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/.well-known/openid-configuration":
            self._json(200, self.authorization_server.discovery())
        elif parsed.path == "/authorize":
            query = parse_qs(parsed.query)
            self.send_response(302)
            self.send_header("Location", f"{query['redirect_uri'][0]}?{urlencode({'code': 'code', 'state': query['state'][0]})}")
            self.end_headers()
        elif parsed.path == "/userinfo" and self.headers["Authorization"] == "Bearer access-token":
            self._json(200, self.authorization_server.userinfo)
        else:
            self.send_error(404)

    def do_POST(self) -> None:
        form = parse_qs(self.rfile.read(int(self.headers.get("Content-Length", "0"))).decode())
        if self.path == "/token" and form.get("client_secret") == [self.authorization_server.client_secret]:
            self._json(200, {"access_token": "access-token", "token_type": "Bearer"})
        else:
            self._json(401, {"error": "invalid_client"})

    def _json(self, status: int, document: dict) -> None:
        body = json.dumps(document).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args) -> None:
        return


@dataclass
class AuthorizationServer:
    url: str
    client_secret: str
    userinfo: dict

    @contextmanager
    def asserting(self, claims: dict) -> Iterator["AuthorizationServer"]:
        """Answer userinfo with ``claims`` over the current ones until the context exits."""
        current = self.userinfo
        self.userinfo = {**current, **claims}
        try:
            yield self
        finally:
            self.userinfo = current

    @property
    def discovery_url(self) -> str:
        return f"{self.url}/.well-known/openid-configuration"

    def discovery(self) -> dict[str, str]:
        return {
            "issuer": self.url,
            "authorization_endpoint": f"{self.url}/authorize",
            "token_endpoint": f"{self.url}/token",
            "userinfo_endpoint": f"{self.url}/userinfo",
        }


@contextmanager
def live_authorization_server(client_secret: str, userinfo: dict) -> Iterator[AuthorizationServer]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), lambda *args: _AuthorizationServerHandler(authorization_server, *args))
    host, port = server.server_address
    authorization_server = AuthorizationServer(f"http://{host}:{port}", client_secret, userinfo)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield authorization_server
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()
