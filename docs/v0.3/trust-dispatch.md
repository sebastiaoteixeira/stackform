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

`trust: idp` is only valid on `oidc` and `saml` providers. JWT bearer dispatch
applies to OIDC providers; SAML providers use their browser-based flow and are
not treated as JWT issuer verifiers. On such a provider
the app mints no token of its own, so app-signing fields (`algorithm`,
`secret`, `ttl`, `refresh`, `delivery`) are rejected. The issuer is derived from
the discovery document, and the accepted audience defaults to the provider's
`client_id` unless `audiences` is set explicitly.

## Signing the app's own tokens

Dispatch decides which tokens the app *verifies*. The complementary question —
how the app *signs* the tokens it mints under `trust: app` — is answered by the
`session` block; see [RS256 session tokens](./rs256-signing.md).
