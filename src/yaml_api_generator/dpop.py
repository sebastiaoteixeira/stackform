import base64
import hashlib
import json
import secrets
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from jwt.algorithms import ECAlgorithm


def generate_private_key_pem() -> str:
    key = ec.generate_private_key(ec.SECP256R1())
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()


def _normalized_htu(url: str) -> str:
    parsed = urlsplit(url)
    host = (parsed.hostname or "").lower()
    default_port = (parsed.scheme.lower(), parsed.port) in {("http", 80), ("https", 443)}
    port = "" if parsed.port is None or default_port else f":{parsed.port}"
    return urlunsplit((parsed.scheme.lower(), f"{host}{port}", parsed.path, "", ""))


@dataclass(frozen=True)
class DPoPProofFactory:
    private_key: ec.EllipticCurvePrivateKey
    public_jwk: dict[str, Any]

    @classmethod
    def from_pem(cls, pem: str) -> "DPoPProofFactory":
        private_key = serialization.load_pem_private_key(pem.encode(), password=None)
        if not isinstance(private_key, ec.EllipticCurvePrivateKey) or not isinstance(
            private_key.curve, ec.SECP256R1
        ):
            raise ValueError("DPoP private key must be an EC P-256 private key")
        public_jwk = json.loads(ECAlgorithm.to_jwk(private_key.public_key()))
        return cls(private_key=private_key, public_jwk=public_jwk)

    def proof(
        self,
        method: str,
        url: str,
        *,
        access_token: str | None = None,
        nonce: str | None = None,
    ) -> str:
        payload: dict[str, Any] = {
            "jti": secrets.token_urlsafe(16),
            "htm": method.upper(),
            "htu": _normalized_htu(url),
            "iat": int(time.time()),
        }
        if access_token is not None:
            payload["ath"] = base64.urlsafe_b64encode(
                hashlib.sha256(access_token.encode()).digest()
            ).rstrip(b"=").decode()
        if nonce is not None:
            payload["nonce"] = nonce
        return jwt.encode(
            payload,
            self.private_key,
            algorithm="ES256",
            headers={"typ": "dpop+jwt", "jwk": self.public_jwk},
        )


async def request_with_dpop(
    client: Any,
    method: str,
    url: str,
    proof_factory: DPoPProofFactory,
    *,
    access_token: str | None = None,
    headers: dict[str, str] | None = None,
    **kwargs: Any,
) -> Any:
    request_headers = dict(headers or {})
    request_headers["DPoP"] = proof_factory.proof(
        method, url, access_token=access_token
    )
    response = await client.request(method, url, headers=request_headers, **kwargs)
    nonce = response.headers.get("DPoP-Nonce")
    if response.status_code not in {400, 401} or not nonce:
        return response
    retry_headers = {
        **request_headers,
        "DPoP": proof_factory.proof(
            method,
            url,
            access_token=access_token,
            nonce=nonce,
        ),
    }
    return await client.request(method, url, headers=retry_headers, **kwargs)
