---
title: Refresh-token rotation
description: Split the login flow into a short-lived access token and a rotating refresh token.
---

# Refresh-token rotation

The optional `session` block turns the login flow from a single long-lived token
into a short-lived access token paired with a rotating refresh token. It reuses
the `session` block introduced for RS256 signing, so `algorithm`, `ttl`, and
`refresh` all live together.

```yaml
session:
  algorithm: HS256   # or RS256; refresh tokens are signed with the same key
  ttl: 900           # access-token lifetime in seconds (default 900 when refresh is on)
  refresh: true      # default false
```

`refresh` defaults to `false`. A spec that omits it — or omits the `session`
block entirely — generates byte-for-byte the same output as before: the login
route returns `{ "token", "user" }` and the access token keeps its
`JWT_EXPIRATION_HOURS` lifetime.

## What turning it on changes

When `refresh: true`:

- The access token becomes short-lived. Its expiry is driven by
  `JWT_ACCESS_TTL_SECONDS` (seeded from `session.ttl`, default `900`) instead of
  `JWT_EXPIRATION_HOURS`.
- Login additionally mints a refresh token and returns
  `{ "token", "refresh_token", "user" }`.
- A `POST /{identity}/refresh` endpoint is generated for every password
  identity. It accepts `{ "refresh_token": "..." }` and returns a fresh
  `{ "token", "refresh_token" }` pair.

Refresh tokens are JWTs signed with the same key as the access token (HS256 or
RS256), carrying `typ: refresh`, a unique `jti`, and a session-family `sid`.
`JWT_REFRESH_TTL_SECONDS` (default 30 days) bounds their lifetime.

## Rotation, reuse detection, and revocation

Every issued refresh token is recorded in the `_refresh_tokens` collection with
its `jti`, family `sid`, `used`, and `revoked` flags. On each refresh:

1. The presented token is verified and its `jti` looked up.
2. An unknown, revoked, or expired token is rejected with `401`.
3. A token already marked `used` is a **reuse**: the entire session family
   (`sid`) is revoked and the request is rejected with `401`. This defeats
   theft — replaying a captured token invalidates the attacker's and the
   victim's tokens alike.
4. Otherwise the token is marked `used` and a new refresh token is issued in the
   same family, so only the latest token in a family is ever valid (rotation).

`revoke_session(sid)` is available for explicit logout / administrative
revocation of a whole family.

## Error codes

- `401 Invalid refresh token` — the refresh token was unknown, expired, already
  rotated (reuse), or belongs to a revoked family.

## Scope

Rotation is generated for the FastAPI backend, whose login flow is MongoDB-backed;
the refresh store uses the same database. The `yaml-api run` dev server does not
mount these generated auth routes, so refresh rotation is exercised at the
generation and unit layers.
