"""Session tokens the dev server mints for itself and verifies on each request.

Environment:
- JWT_EXPIRATION_HOURS: token lifetime in hours (default: 24)
- JWT_SECRET: HS256 signing secret
- JWT_PRIVATE_KEY: RS256 PEM-encoded private key
- JWT_RETIRED_PUBLIC_KEY: RS256 PEM-encoded public key kept verifiable during rotation
"""

import json
import logging
import os
import time
from base64 import urlsafe_b64encode
from hashlib import sha256

import jwt
from cryptography.hazmat.primitives import serialization
from jwt.algorithms import RSAAlgorithm

from yaml_api_generator.utils.rsa_keys import generate_private_key_pem
from ..server_context import RuntimeSessionConfig

logger = logging.getLogger(__name__)

DEV_SECRET = "yaml-api-dev-secret-change-me"
JWKS_PATH = "/.well-known/jwks.json"


class SessionTokens:
    """Mints and verifies the session tokens this application issues itself."""

    algorithm = ""

    def create(self, sub: str, identity_collection: str) -> str:
        now = int(time.time())
        payload = {
            "sub": sub,
            "identity_collection": identity_collection,
            "iat": now,
            "exp": now + _expiration_hours() * 3600,
        }
        return jwt.encode(
            payload, self._signing_key(), algorithm=self.algorithm, headers=self._headers()
        )

    def decode(self, token: str) -> dict | None:
        try:
            return jwt.decode(
                token, self._verification_key(token), algorithms=[self.algorithm]
            )
        except jwt.InvalidTokenError:
            return None

    def public_jwks(self) -> dict:
        """The public half of every key whose tokens this app still accepts."""
        return {"keys": []}

    def _headers(self) -> dict:
        return {}

    def _signing_key(self) -> str:
        raise NotImplementedError

    def _verification_key(self, token: str):
        raise NotImplementedError


class SymmetricSessionTokens(SessionTokens):
    algorithm = "HS256"

    def __init__(self, secret: str) -> None:
        self._secret = secret

    def _signing_key(self) -> str:
        return self._secret

    def _verification_key(self, token: str) -> str:
        return self._secret


class AsymmetricSessionTokens(SessionTokens):
    algorithm = "RS256"

    def __init__(self, private_pem: str, retired_public_pems: tuple[str, ...] = ()) -> None:
        self._private_pem = private_pem
        private_key = serialization.load_pem_private_key(private_pem.encode(), password=None)
        signing_jwk = self._public_jwk(private_key.public_key())
        retired_jwks = [
            self._public_jwk(serialization.load_pem_public_key(pem.encode()))
            for pem in retired_public_pems
        ]
        self._jwks = [signing_jwk, *retired_jwks]
        self._verification_keys = {
            entry["kid"]: jwt.PyJWK.from_dict(entry).key for entry in self._jwks
        }
        self._token_headers = {"kid": signing_jwk["kid"]}

    def public_jwks(self) -> dict:
        return {"keys": self._jwks}

    def _headers(self) -> dict:
        return self._token_headers

    def _signing_key(self) -> str:
        return self._private_pem

    def _verification_key(self, token: str):
        key = self._verification_keys.get(jwt.get_unverified_header(token).get("kid"))
        if key is None:
            raise jwt.DecodeError("Token was not signed by a published key")
        return key

    @classmethod
    def _public_jwk(cls, key) -> dict:
        entry = json.loads(RSAAlgorithm.to_jwk(key))
        canonical = json.dumps(
            {"e": entry["e"], "kty": entry["kty"], "n": entry["n"]},
            separators=(",", ":"),
            sort_keys=True,
        )
        kid = urlsafe_b64encode(sha256(canonical.encode()).digest()).rstrip(b"=").decode()
        return {**entry, "kid": kid, "use": "sig", "alg": cls.algorithm}


def build_session_tokens(session: RuntimeSessionConfig) -> SessionTokens:
    """Build the token minter the spec asks for, sourcing keys from the environment."""
    if not session.uses_asymmetric:
        return SymmetricSessionTokens(os.environ.get("JWT_SECRET", DEV_SECRET))
    retired = _pem_from_env("JWT_RETIRED_PUBLIC_KEY")
    return AsymmetricSessionTokens(
        _private_key_pem(), (retired,) if retired else ()
    )


def _private_key_pem() -> str:
    configured = _pem_from_env("JWT_PRIVATE_KEY")
    if configured:
        return configured
    logger.warning(
        "JWT_PRIVATE_KEY is not set; signing session tokens with an ephemeral key "
        "that is discarded when this process exits"
    )
    return generate_private_key_pem()


def _pem_from_env(name: str) -> str:
    return os.environ.get(name, "").strip().replace("\\n", "\n")


def _expiration_hours() -> int:
    return int(os.environ.get("JWT_EXPIRATION_HOURS", "24"))
