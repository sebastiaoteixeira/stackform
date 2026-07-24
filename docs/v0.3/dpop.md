# DPoP for the OIDC client

DPoP (Demonstrating Proof of Possession, [RFC 9449](https://datatracker.ietf.org/doc/html/rfc9449))
sender-constrains tokens to a client-held key pair, so a stolen access token
cannot be replayed by anyone who does not also hold the private key. Enable it on
an OIDC provider to match a provider that issues DPoP-bound tokens.

## Enabling

DPoP is off by default. A spec that does not set `dpop` generates byte-identical
output. Opt in per provider:

```yaml
providers:
  keycloak:
    type: oidc
    client_id: my-app
    discovery_url: "https://sso.example.com/realms/app/.well-known/openid-configuration"
    dpop: true
```

`dpop` and `pkce` are independent and may be combined on the same provider.

## What the generated client emits

The client generates an ephemeral EC (P-256 / ES256) key pair at module load and
signs a fresh DPoP proof JWT for every outbound call to the provider. Each proof
carries a `typ: dpop+jwt` header with the public `jwk`, and claims `jti`, `htm`
(HTTP method), `htu` (target URI without query), and `iat`. The proof is sent in
the `DPoP` header.

- On the token exchange the client sends a `DPoP` proof for `POST <token_endpoint>`.
- On the userinfo call the access token is presented as `Authorization: DPoP <token>`
  (not `Bearer`) together with a `DPoP` proof for `GET <userinfo_endpoint>` whose
  `ath` claim is `BASE64URL(SHA256(access_token))`, binding the proof to that token.

The key pair lives entirely within the backend process; both the token exchange
and the userinfo call happen inside the same callback request, so a single key
signs both proofs.

## Error codes

DPoP adds no new backend error codes. A provider that rejects a proof surfaces
through the existing `401 Token exchange failed` / `401 Failed to fetch user info`
responses.

## Testing note

The `yaml-api run` dev server does not mount the OIDC provider routes, so the
DPoP-bound token/userinfo round-trip cannot be driven end-to-end from the dev
server. Coverage lives at the generation layer (the emitted client carries the
key pair, the proof helper, the `DPoP` headers, and the `DPoP`-scheme
`Authorization`); the live round-trip is exercised against a real provider that
issues DPoP-bound tokens.
