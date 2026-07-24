# Resource-server IdP token verification

A `trust: idp` provider makes the app a pure resource server: the client keeps
carrying the IdP's own token and the app verifies it on every request, minting
no session token of its own. Sessions do not apply.

## What is verified

For a bearer token whose `iss` matches the provider's issuer:

- **Signature** against the IdP's JWKS. The signing key is selected by the
  token's `kid` header. `RS256` and `ES256` are accepted; symmetric algorithms
  (e.g. `HS256`) are never accepted, so a token signed with a shared secret can
  never impersonate an IdP.
- **Issuer** (`iss`) against the provider's configured issuer, or the issuer
  read from the discovery document when the spec omits it.
- **Audience** (`aud`) against `audiences` when set, otherwise against
  `client_id`.
- **Expiry** (`exp`), rejecting expired tokens.

A token that fails any check is rejected with `401`; it is never retried as an
app token or an api key.

## JWKS fetching and caching

The JWKS is fetched from the `jwks_uri` in the provider's discovery document and
cached in-process, so only the first request per provider touches the network.
When a token presents a `kid` absent from the cache, the JWKS is refetched once
to pick up rotated keys before the token is rejected.

## Claim mapping and provisioning

Verified claims are mapped to a local user through the provider binding's
`claim_mapping`, following the existing OIDC provisioning rules: an unknown user
is auto-provisioned when the binding sets `auto_provision`, and rejected
otherwise. A token that carries no identifier claim (a machine-to-machine token)
resolves to a service principal and creates no user row.

## Testing note

`yaml-api run` does not mount provider routes, so this behavior is covered by
unit and component tests at the provider/middleware layer rather than through
the dev server end to end.
