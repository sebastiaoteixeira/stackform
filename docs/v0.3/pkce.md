# PKCE for the OIDC client

Proof Key for Code Exchange ([RFC 7636](https://datatracker.ietf.org/doc/html/rfc7636))
binds an OIDC authorization code to the client that requested it, so a stolen
code cannot be redeemed by anyone else. Enable it on an OIDC provider to match a
Keycloak client configured with **Require PKCE**.

## Enabling

PKCE is off by default. Opt in per application OIDC provider:

```yaml
providers:
  keycloak:
    type: oidc
    client_id: my-app
    discovery_url: "https://sso.example.com/realms/app/.well-known/openid-configuration"
    pkce: true
```

PKCE is supported by `yaml-api run` and generated FastAPI backends. DRF and raw
ASGI builds reject PKCE at build time because those targets do not implement
OIDC client routes.

## What the client emits

On the login redirect the client creates a random `code_verifier`, derives the
`code_challenge` as `BASE64URL(SHA256(verifier))`, and adds `code_challenge`
plus `code_challenge_method=S256` to the authorization request. The verifier is
held in a short-lived (`max_age=300`), `HttpOnly`, `SameSite=Lax` cookie scoped
to the provider's callback path (`secure` when the request is HTTPS).

Every OIDC login, with or without PKCE, also creates a random `state` value. The
authorization request and a separate short-lived callback-scoped cookie carry
that value. The callback compares both values in constant time before any token
exchange, preventing login CSRF.

On the callback the client reads the verifier cookie and sends it as
`code_verifier` on the token exchange, then clears the cookie. A callback with a
missing or expired verifier cookie is rejected.

The `S256` method is always used; the plain method is never emitted.

## Error codes

- `400 Invalid OIDC state` - the state parameter or its correlation cookie is
  missing, expired, or does not match.
- `400 Missing PKCE verifier` - the callback ran without the verifier cookie
  (expired, cleared, or the login step was skipped).

## Keycloak client configuration

On the Keycloak client set **Proof Key for Code Exchange Code Challenge Method**
to `S256` (Advanced settings), which turns on Require PKCE. Login then completes
only when the verifier matches the challenge.

`pkce` is an OIDC application-client option and is rejected for providers using
`trust: idp`, which validate incoming resource-server tokens rather than
initiating an authorization-code flow.
