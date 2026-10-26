---
title: Dual-trust token dispatch
description: "How a spec that mixes an app-trust login with a trust: idp provider picks a verifier for each bearer token by its iss claim."
---

# Dual-trust token dispatch

When a spec mixes an app-trust login (`password`, `apiKey`, or app-trust OIDC)
with a `trust: idp` provider, the generated FastAPI backend and the FastAPI
development server verify each bearer token against a single verifier chosen
strictly by its `iss` claim:

- `iss` matches a trusted IdP issuer -> the token is verified against that IdP,
  checking `aud` and `iss` against the provider's configuration. What that
  verification covers, and how each failure is answered, is described in
  [Resource-server IdP token verification](./verify-idp.md).
- `iss` matches no trusted issuer -> the request is rejected with `401` and the
  message `Untrusted token issuer`. A foreign IdP token is never retried as an
  app token or an api key.
- No `iss` claim -> the bearer is an app-minted token or an opaque api key and
  is resolved by the app-token and credential paths.

There is no "try every verifier" fallback: the issuer alone decides the single
path a token takes, so a token accepted by one issuer can never be silently
validated by another.

## Provider requirements

`trust` is an `oidc` provider key; a `saml` provider has no `trust` and is never
a JWT issuer verifier. Under `trust: idp` the provider takes `issuer` and
`audiences` and rejects `client_secret`, `pkce` and `dpop`; under `trust: app`
it rejects `issuer` and `audiences`. Each violation is a
`SCHEMA_VALIDATION_ERROR`. The issuer is derived from the discovery document
unless `issuer` is set. The accepted audience is `audiences`, or the provider's
`client_id` when `audiences` is omitted, in which case generation reports the
warning `TRUST_IDP_AUDIENCE_DEFAULTED`.

## Signing the app's own tokens

Dispatch decides which tokens the app *verifies*. The complementary question —
how the app *signs* the tokens it mints under `trust: app` — is answered by the
`session` block; see [RS256 session tokens](./rs256-signing.md).
