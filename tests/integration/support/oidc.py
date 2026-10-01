"""A live OIDC issuer: discovery and JWKS over HTTP, and RS256 tokens signed with its key."""

import json
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

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
