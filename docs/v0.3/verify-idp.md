---
title: Resource-server IdP token verification
description: How a trust: idp provider's tokens are verified on every request, and which backends implement it.
---

# Resource-server IdP token verification

A `trust: idp` provider makes the app a pure resource server: the client keeps
carrying the IdP's own token and the app verifies it on every request, minting
no session token of its own. Sessions do not apply.

Verification is implemented by the generated FastAPI backend and the FastAPI
development server. The `drf` and `raw` backends cannot verify an IdP token per
request, so they refuse such a spec instead of emitting code that skips the
check: generation aborts with the coded error `BACKEND_FEATURE_UNSUPPORTED` on
`providers.<name>.trust`, and no output is written. Only OIDC providers are
verified this way; a SAML provider uses its browser-based flow and is not a JWT
issuer verifier. Which verifier a bearer token reaches is decided by its `iss`
claim alone &mdash; see [Dual-trust token dispatch](./trust-dispatch.md).

## What is verified

For a bearer token whose `iss` matches the provider's issuer:

- **`kid` header.** The signing key is selected by the token's `kid`. A token
  whose header carries no `kid` is rejected before any network call: no JWKS is
  fetched and no key is trusted.
- **Signature** against the key bearing that `kid` in the IdP's JWKS. Only
  `RS256` and `ES256` are accepted; a symmetric algorithm (e.g. `HS256`) is
  refused for its algorithm, so a token signed with a shared secret can never
  impersonate an IdP.
- **Required claims.** `exp`, `iss`, `aud` and `sub` are all mandatory
  (`REQUIRED_CLAIMS`). A token missing any one of them is rejected &mdash;
  including a token with no `exp`, which would otherwise never expire.
- **Expiry** (`exp`), rejecting expired tokens.
- **Not before** (`nbf`). When the token carries `nbf`, a token presented before
  that instant is rejected. `nbf` itself is not required to be present.
- **Issuer** (`iss`) against the provider's configured issuer, or the issuer
  read from the discovery document when the spec omits it.
- **Audience** (`aud`) against `audiences` when set, otherwise against
  `client_id`.

Verification yields either a full claim set or nothing; there is no partial
acceptance, and a token rejected here is never retried as an app token or an
api key.

## Failure responses

Every rejection on this path answers `401`. The distinct messages a client sees:

| Condition | Status | `detail` |
| --- | --- | --- |
| `iss` present but matching no configured IdP issuer | `401` | `Untrusted token issuer` |
| Verification fails: missing `kid`, a `kid` still unknown after the refetch, bad signature, symmetric algorithm, wrong `aud` or `iss`, expired, `nbf` in the future, a required claim missing, or a malformed token | `401` | `Invalid IdP token` |
| Claims verified, no local record for the token's `sub`, and the binding does not set `auto_provision` | `401` | `User not found and auto-provisioning is disabled` |
| Claims verified, but the provider has no identity binding to resolve the token against | `401` | `Untrusted token issuer` |

In the generated backend these are raised as `HTTPException(status_code=401)`.
In the development server they are raised as `UnauthorizedError`, which the
FastAPI factory and the ASGI runner both map to `401`, and which the IdP
middleware returns directly as a `401` JSON body. No case on this path returns
`403`, and none falls through to an anonymous principal.

A token carrying no identifier claim is not a failure; see
[Claim mapping and provisioning](#claim-mapping-and-provisioning).

## When the IdP is unreachable

An unreachable discovery or JWKS endpoint is deliberately not reported as an
invalid token. `verify_idp_token` catches only `jwt.InvalidTokenError`, so the
`httpx` error from a failed connection or a non-2xx `raise_for_status()`
propagates out of the verifier untouched: an IdP outage never becomes a claim
that the presented token is bad.

Where that propagating error surfaces differs by runtime:

- In the development server nothing catches it, so the request fails as a
  server error rather than an authentication error.
- In the generated backend, the IdP middleware logs `IdP authentication failed`
  and answers `401` with `detail` `Authentication failed` for an error raised
  while resolving the token &mdash; a message deliberately distinct from
  `Invalid IdP token`. The discovery fetch that matches the token's issuer to a
  provider runs before that guard, so an outage there propagates as a server
  error instead.

## JWKS and discovery caching

Discovery documents and key sets are cached in-process in a bounded cache whose
entries expire, so a key withdrawn at the IdP stops verifying tokens once its
entry ages out rather than being trusted for the lifetime of the process.

- Development server: `JWKS_CACHE_TTL_SECONDS = 300.0` for the JWKS cache; the
  discovery cache uses the `TTLCache` defaults `DEFAULT_TTL_SECONDS = 300.0` and
  `DEFAULT_MAX_ENTRIES = 128`, and the JWKS cache takes that same default bound.
- Generated backend, in the `idp_auth` module vendored into the output:
  `CACHE_TTL_SECONDS = 300.0` and `CACHE_MAX_ENTRIES = 128` for both caches.

So an entry is served from memory for at most 300 seconds, and each cache holds
at most 128 entries, dropping the least recently used beyond that bound.

When a token presents a `kid` absent from the cached key set, the JWKS is
refetched exactly once and the cached entry replaced, picking up a rotated key;
if the `kid` is still unknown after that single refetch, the token is rejected.
A token with no `kid` triggers no fetch at all.

## Claim mapping and provisioning

Under `trust: idp` the IdP's `sub` is the primary key: the local record is
looked up by the identity collection's id field equal to `sub`, and provisioned
with that same value, so the principal's `sub`, the record's id field and the
token's `sub` are one key. The remaining fields come from the binding's
`claim_mapping`, following the existing OIDC provisioning rules: an unknown user
is auto-provisioned when the binding sets `auto_provision`, and rejected
otherwise.

A token that carries no identifier claim (a machine-to-machine token) resolves
to a service principal marked `is_service` with no record, and creates no user
row.

## Testing note

`yaml-api run` does not mount provider routes, so this behaviour is covered by
unit and component tests at the provider and middleware layer rather than
through the dev server end to end.
