# Dual-trust token dispatch

When a spec mixes an app-trust login (`password`, `apiKey`, or app-trust OIDC)
with a `trust: idp` provider, generated backends and the dev server verify each
bearer token against a single verifier chosen strictly by its `iss` claim:

- `iss` matches a trusted IdP issuer -> the token is verified against that IdP,
  checking `aud` and `iss` against the provider's configuration.
- `iss` matches no trusted issuer -> the request is rejected with `401` and the
  message `Untrusted token issuer`. A foreign IdP token is never retried as an
  app token or an api key.
- No `iss` claim -> the bearer is an app-minted token or an opaque api key and
  is resolved by the app-token and credential paths.

There is no "try every verifier" fallback: the issuer alone decides the single
path a token takes, so a token accepted by one issuer can never be silently
validated by another.

## Provider requirements

`trust: idp` is only valid on `oidc` and `saml` providers. On such a provider
the app mints no token of its own, so app-signing fields (`algorithm`,
`secret`, `ttl`, `refresh`, `delivery`) are rejected. The issuer is derived from
the discovery document, and the accepted audience defaults to the provider's
`client_id` unless `audiences` is set explicitly.
