# PKCE for the OIDC client

Proof Key for Code Exchange ([RFC 7636](https://datatracker.ietf.org/doc/html/rfc7636))
binds an OIDC authorization code to the client that requested it, so a stolen
code cannot be redeemed by anyone else. Enable it on an OIDC provider to match a
Keycloak client configured with **Require PKCE**.

## Enabling

PKCE is off by default. A spec that does not set `pkce` generates byte-identical
output. Opt in per provider:

```yaml
providers:
  keycloak:
    type: oidc
    client_id: my-app
    discovery_url: "https://sso.example.com/realms/app/.well-known/openid-configuration"
    pkce: true
```

## What the generated client emits

On the login redirect the client creates a random `code_verifier`, derives the
`code_challenge` as `BASE64URL(SHA256(verifier))`, and adds `code_challenge`
plus `code_challenge_method=S256` to the authorization request. The verifier is
held in a short-lived (`max_age=300`), `HttpOnly`, `SameSite=Lax` cookie scoped
to the provider's callback path (`secure` when the request is HTTPS).

On the callback the client reads the verifier cookie and sends it as
`code_verifier` on the token exchange, then clears the cookie. A callback with a
missing or expired verifier cookie is rejected.

The `S256` method is always used; the plain method is never emitted.

## Error codes

- `400 Missing PKCE verifier` - the callback ran without the verifier cookie
  (expired, cleared, or the login step was skipped).

## Keycloak client configuration

On the Keycloak client set **Proof Key for Code Exchange Code Challenge Method**
to `S256` (Advanced settings), which turns on Require PKCE. Login then completes
only when the verifier matches the challenge.

## Testing note

The `yaml-api run` dev server does not mount the OIDC provider routes, so the
PKCE authorization/callback round-trip cannot be driven end-to-end from the dev
server. Coverage lives at the generation layer (the emitted client carries the
challenge, verifier cookie, and token-exchange verifier); the live round-trip is
exercised against a real Keycloak client with Require PKCE enabled.
