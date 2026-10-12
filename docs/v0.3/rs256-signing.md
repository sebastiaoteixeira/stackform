---
title: RS256 session tokens
description: Sign app-minted session tokens with an RSA private key and publish the public key over JWKS, with a key-rotation story.
---

## The `session` block

The optional top-level `session` block selects the algorithm used to sign the
JWTs the app mints at login and at OIDC/SAML callbacks:

```yaml
session:
  algorithm: RS256   # HS256 (default) | RS256
```

`algorithm` defaults to `HS256`. A spec that omits `session` (or sets
`algorithm: HS256`) is byte-identical to before: tokens are signed with the
symmetric `JWT_SECRET`, and no JWKS endpoint is emitted. `session` is accepted
under both `version: "0.2"` and `version: "0.3"`.

This is the `trust: app` direction: the app signs tokens it issues itself. It is
independent of [`trust: idp`](verify-idp.md), where the app verifies tokens
minted by an external identity provider. A spec may use both, and the two never
share key material: `session.algorithm` governs the app's own signing key, while
each `trust: idp` provider is verified against that provider's JWKS. See
[trust dispatch](trust-dispatch.md) for how a login is routed.

## HS256 versus RS256

| | HS256 | RS256 |
| --- | --- | --- |
| Key material | one shared secret (`JWT_SECRET`) | RSA key pair |
| Who can verify | only holders of the secret | anyone with the public key |
| Signing setting | `JWT_SECRET` | `JWT_PRIVATE_KEY` |
| Public key exposure | none | `GET /.well-known/jwks.json` |

Choose RS256 when a separate service must verify the app's tokens without
sharing the signing key. The public key travels over JWKS; the private key
never leaves the app.

## What RS256 generates

- **`JWT_PRIVATE_KEY`** replaces `JWT_SECRET` in the generated settings. It is a
  required secret holding a PEM-encoded RSA private key, with no default: an app
  started without it fails at import with a settings validation error rather
  than falling back to a weaker or built-in key.
- **`JWT_RETIRED_PUBLIC_KEY`** is an optional PEM-encoded RSA *public* key. When
  set, tokens signed by it stay verifiable and its JWK is published alongside the
  signing key. See [key rotation](#key-rotation) below.
- **`jwt_utils`** signs with `RS256`, stamps each token header with a `kid` (the
  RFC 7638 thumbprint of the public JWK), derives the public key from the private
  key at startup, and exposes `public_jwks()`.
- **A JWKS route** serves the public key set at `GET /.well-known/jwks.json`,
  mounted at the application root (outside `basePath`) so verifiers find it at
  the conventional location. It is unauthenticated by design, and publishes only
  `kty`, `n`, `e`, `kid`, `use` and `alg` — the private components (`d`, `p`,
  `q`, `dp`, `dq`, `qi`) are never serialised into it.

A verifier fetches the JWKS, matches the token's `kid` to a key, and validates
the signature. No secret is shared.

## Backend support

RS256 signing and the JWKS endpoint are implemented by **all three generated
backends and by the dev server**. What differs is only where the private key
comes from.

| Target | JWKS route | Key source |
| --- | --- | --- |
| `fastapi` | `routes/jwks.py`, mounted on the app root | the generated environment file is seeded with a fresh 2048-bit key; the example file carries a `<jwt_private_key>` placeholder |
| `drf` | `api/views/jwks.py`, wired in the project `urls.py` | `JWT_PRIVATE_KEY` must be supplied by the environment |
| `raw` | `routes/jwks.py`, registered in `app.py` | `JWT_PRIVATE_KEY` must be supplied by the environment |
| `stackform run` | injected into the runtime route table | `JWT_PRIVATE_KEY` from the environment; otherwise an ephemeral key, see below |

Only the `fastapi` target emits environment files, so only it can seed a key at
generation time. For `drf` and `raw` the key is a deployment input: with
`JWT_PRIVATE_KEY` unset, the generated app raises a settings validation error on
startup instead of serving traffic.

## The dev server

`stackform run` honours `session.algorithm` too. With `RS256` it mounts the same
`/.well-known/jwks.json` route and mints `kid`-stamped RS256 tokens.

If `JWT_PRIVATE_KEY` is set it is used; PEM newlines may be escaped as `\n`, as
in a dotenv value. If it is unset, the dev server generates an RSA key for the
lifetime of the process and logs a warning. Tokens minted before a restart stop
verifying after it — acceptable for local development, and the reason the
generated backends refuse to do the same.

## Key rotation

The signing key lives entirely in `JWT_PRIVATE_KEY`; the public key and its
`kid` are derived from it, so there is a single source of truth and nothing to
keep in sync.

To rotate without invalidating live sessions:

1. Set `JWT_RETIRED_PUBLIC_KEY` to the public half of the current key.
2. Set `JWT_PRIVATE_KEY` to a new private key.
3. Restart. New tokens carry the new `kid`, and `/.well-known/jwks.json`
   publishes both keys, so tokens signed by either remain verifiable.
4. Once every token issued under the old key has expired (at most
   `JWT_EXPIRATION_HOURS`), clear `JWT_RETIRED_PUBLIC_KEY` and restart again.

Skipping step 1 is a hard cutover: tokens signed by the previous key are
rejected immediately, because a token whose `kid` is not published is refused
before any signature check runs. Verifiers that cache JWKS refresh on an unknown
`kid` and pick up the new key automatically.

## Security properties

- The private key is never serialised into the JWKS response and never logged.
  Only public JWK fields are published.
- Every minted token carries a `kid` that matches an entry in the JWKS.
- The accepted algorithm is pinned to a single value at decode time. A token
  re-signed as HS256 using the published public key as the HMAC secret is
  rejected, as is an `alg: none` token, and so is an RS256 token carrying no
  `kid` or an unrecognised one.
- Verification failures return `None` from `decode_jwt_token` and surface as a
  generic 401; no exception text from the JWT library reaches the client.

## Generation-time errors

`session.algorithm: RS256` on a spec that never mints a session token — no
password identity, no app-trust OIDC or SAML login — is rejected at generation
time with `SESSION_ALGORITHM_UNUSED` rather than silently emitting an unused key
pair and JWKS endpoint. Either give an identity a way to log in, or drop the
`session` block.
