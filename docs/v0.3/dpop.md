# DPoP for the OIDC client

DPoP (Demonstrating Proof of Possession, [RFC 9449](https://datatracker.ietf.org/doc/html/rfc9449))
sender-constrains tokens to a client-held key pair, so a stolen access token
cannot be replayed by anyone who does not also hold the private key. Enable it on
an OIDC provider to match a provider that issues DPoP-bound tokens.

## Enabling

DPoP is off by default. Opt in per application OIDC provider:

```yaml
providers:
  keycloak:
    type: oidc
    client_id: my-app
    discovery_url: "https://sso.example.com/realms/app/.well-known/openid-configuration"
    dpop: true
```

`dpop` and `pkce` are independent and may be combined on the same provider.
DPoP is supported by `yaml-api run` and generated FastAPI backends. DRF and raw
ASGI builds reject it because those targets do not implement OIDC client routes.
It is also rejected with `trust: idp`, where the application verifies incoming
tokens rather than acting as the OAuth client that obtains them.

## Key configuration

Each DPoP provider requires `<PROVIDER>_DPOP_PRIVATE_KEY`, an EC P-256 private
key in PEM form. Generated FastAPI projects create this secret once in `.env`
and expose a placeholder in `.env.example`. Every worker loads the same key, so
token binding remains valid across worker and process restarts. For
`yaml-api run`, set the environment variable before startup; `\\n`-escaped PEM
values are accepted.

## What the client emits

The client signs a fresh ES256 DPoP proof JWT for every outbound call. Each
proof carries a `typ: dpop+jwt` header with the public `jwk`, and claims `jti`,
`htm` (HTTP method), normalized `htu` (target URI without query or fragment),
and `iat`. The proof is sent in the `DPoP` header.

- On the token exchange the client sends a `DPoP` proof for `POST <token_endpoint>`.
- On the userinfo call the access token is presented as `Authorization: DPoP <token>`
  (not `Bearer`) together with a `DPoP` proof for `GET <userinfo_endpoint>` whose
  `ath` claim is `BASE64URL(SHA256(access_token))`, binding the proof to that token.

The client requires the token response's `token_type` to be `DPoP`; a Bearer
token is rejected instead of being treated as sender-constrained. If the token
or resource server answers with `DPoP-Nonce`, the request is retried once with a
new proof containing that nonce.

## Error codes

- Startup fails if `<PROVIDER>_DPOP_PRIVATE_KEY` is missing or is not an EC P-256
  private key.
- `401 Provider did not issue a DPoP-bound token` - the token response did not
  identify the access token as DPoP-bound.
- Existing `401 Token exchange failed` and `401 Failed to fetch user info`
  responses surface provider rejection after the single nonce retry.
- `BACKEND_FEATURE_UNSUPPORTED` - a DRF or raw ASGI build requested DPoP.
- `TRUST_IDP_APP_FIELD_FORBIDDEN` - `dpop` was set on a `trust: idp` provider.
