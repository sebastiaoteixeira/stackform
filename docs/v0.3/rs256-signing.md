---
title: RS256 session tokens
description: Sign app-minted session tokens with an RSA private key and publish the public key over JWKS, with a key-rotation story.
---

## The `session` block

The optional top-level `session` block selects the algorithm used to sign the
JWTs the app mints at login and OIDC/SAML callbacks:

```yaml
session:
  algorithm: RS256   # HS256 (default) | RS256
```

`algorithm` defaults to `HS256`. A spec that omits `session` (or sets
`algorithm: HS256`) is byte-identical to before: tokens are signed with the
symmetric `JWT_SECRET`, and no JWKS endpoint is emitted. `session` is accepted
under both `version: "0.2"` and `version: "0.3"`.

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

- **`JWT_PRIVATE_KEY`** replaces `JWT_SECRET` in `settings.py`. It is a required
  secret holding a PEM-encoded RSA private key. The generated `.env` is seeded
  with a fresh 2048-bit key (double-quoted with escaped newlines so dotenv
  restores the PEM); `.env.example` carries a `<jwt_private_key>` placeholder.
- **`dependencies/jwt_utils.py`** signs with `RS256`, stamps each token header
  with a `kid` (the RFC 7638 thumbprint of the public JWK), derives the public
  key from the private key at startup, and exposes `public_jwks()`.
- **`routes/jwks.py`** serves the public key set at `GET /.well-known/jwks.json`,
  mounted at the application root (outside `basePath`) so verifiers can find it
  at the conventional location.

A verifier fetches the JWKS, matches the token's `kid` to a key, and validates
the signature. No secret is shared.

## Key management and rotation

The signing key lives entirely in the `JWT_PRIVATE_KEY` environment variable;
the public key and its `kid` are derived from it, so there is a single source of
truth and nothing to keep in sync.

To rotate:

1. Generate a new RSA private key and set `JWT_PRIVATE_KEY` to it.
2. Restart the app. The derived `kid` changes, so newly minted tokens carry the
   new `kid` and `/.well-known/jwks.json` immediately serves the new key.
3. Verifiers that cache JWKS refresh on an unknown `kid` and pick up the new
   key automatically.

Tokens signed by the previous key stay valid only until they expire. Keep
`JWT_EXPIRATION_HOURS` short enough that the rotation window is acceptable, or
drain sessions before rotating. Because the app derives the public key from the
private key, rotation is a single-variable change with no separate public-key
deployment step.
