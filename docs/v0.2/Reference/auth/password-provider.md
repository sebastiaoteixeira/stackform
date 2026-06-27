---
title: "Password Provider"
description: Username/password authentication with PBKDF2-SHA256 hashing, JWT issuance, and per-request Basic auth for an auth entity.
---

Enables username/password authentication for an auth entity. The provider hashes
passwords with PBKDF2-SHA256, issues a JWT on login, and also accepts HTTP Basic
credentials on any request.

## Syntax

```yaml
version: "0.2"

api:
  basePath: /api
  version: v1
  operations:
    auth:
      register: true
      login: true

entities:
  myEntity:
    type: auth
    auth:
      identifier: email
      via: password
    fields:
      id: { type: id }
      email: { type: string, required: true, unique: true }
      displayName: { type: string, required: true }

repositories:
  myCollection:
    entity: myEntity

services:
  myCollection:
    repository: myCollection

controllers:
  myCollection:
    service: myCollection
    base_path: /my-collection
    access: public
    operations:
      register: { access: public }
      login: { access: public }
```

The login/register endpoints in the rest of this page assume the `api:` block above,
so the URLs are `/api/v1/...`. Drop `version` and they become `/api/...`; drop the
whole `api:` block and `basePath` still defaults to `/api`.

> **Enforcement status**
>
> Roles (exact match), `<entity>:*` scoping, and ownership/ABAC `when` rules
> are enforced by the generated FastAPI backend, the generated DRF backend, and the
> `yaml-api run` dev server alike. A request that fails a rule gets 401 (missing or
> invalid credentials), 403 (authenticated but not allowed), or 404 (record not
> found, checked before ownership). Two current limitations: role hierarchy (for
> example `admin` inheriting `moderator`) is accepted in YAML but not yet applied
> during enforcement -- only exact role matches are checked; and conditional or
> ownership rules require a v0.2 spec, because v0.1 specs do not parse `when` rules.

## Register and login are off by default

The `register` and `login` endpoints are NOT generated unless you enable them under
`api.operations.auth`:

```yaml
api:
  operations:
    auth:
      register: true
      login: true
```

With neither enabled, the auth entity still authenticates requests (Bearer JWT, API
key, or Basic), but there is no built-in endpoint to create accounts or exchange
credentials for a token.

## Options

The provider is configured under the entity's `auth:` block.

| Field | Required | Type | Description |
|-------|----------|------|-------------|
| `identifier` | effectively yes | string (field name) | The field used as the login username. Not schema-enforced, but login needs it. Common values: `email`, `username`. |
| `via` | effectively yes | string or list | Built-in providers to enable. Use `password` here; may be a list (for example `[password, apiKey]`) to combine built-in providers. A list entry may also be an object declaring an inline provider binding (`provider`, `identifier`, `claim_mapping`, `auto_provision`) -- equivalent to an `auth.bindings` entry. See [Auth overview](./overview.md#auth-block). |
| `roles` | no | string (field name) | Names an existing `enum` field that carries the principal's role. See [Roles overview](../roles/overview.md). |
| `bindings` | no | list | External identity providers (OIDC/SAML). See [Login, SSO, and the token flow](./login-and-sso.md) and [Claim mapping](./claim-mapping.md). |

The `identifier` field should declare `unique: true` so two accounts cannot share a
login value. Note that `unique` is declarative metadata only -- it is not enforced
with a MongoDB index, so uniqueness is not guaranteed at write time.

Declaring a `password` or `passwordHash` field in `fields:` is rejected at parse
time -- both are implicit (see Errors below).

## Generated Endpoints

With `register` and `login` enabled, the engine generates two routes on the auth
entity's repository (here the `myCollection` repository, so the collection segment is
`my-collection`):

| Method | Path | Description |
|--------|------|-------------|
| POST | `{basePath}[/{version}]/{collection}/register` | Create a new account with a hashed password |
| POST | `{basePath}[/{version}]/{collection}/login` | Authenticate and receive a JWT |

With the `api:` block above and the `users` repository, that resolves to
`POST /api/v1/users/register` and `POST /api/v1/users/login`.

## Register Request

Register reuses the standard create pipeline. A `password` field is accepted on the
register payload even though it is not declared in `fields:`; the create step pops it
and stores only the hash.

```json
POST /api/v1/users/register
{
  "email": "alice@example.com",
  "displayName": "Alice",
  "password": "s3cr3t"
}
```

Returns the created record. The stored hash lives under `_auth.passwordHash`, and
read responses strip every underscore-prefixed key, so `_auth` (and therefore the
hash) never appears in the response.

## Login Request

```json
POST /api/v1/users/login
{
  "email": "alice@example.com",
  "password": "s3cr3t"
}
```

Returns the JWT plus a sanitized user record:

```json
{
  "token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "user": {
    "id": "0192...",
    "email": "alice@example.com",
    "displayName": "Alice"
  }
}
```

The `user` object excludes `password`, `_id`, and `_auth`.

## Token Format

The JWT is signed with HS256 and carries only identity, not roles:

```json
{
  "sub": "<id field value>",
  "identity_collection": "<collection name>",
  "iat": 1700000000,
  "exp": 1700086400
}
```

- `sub` is the record's id-field value (NOT the identifier field). Access rules
  reference it as `principal.sub`.
- `identity_collection` names which auth collection the principal belongs to.
- Roles are NOT in the token. On every authenticated request the backend re-reads
  the record from MongoDB and resolves roles from the `auth.roles` enum field, so a
  role change applies immediately without re-issuing the token.

## Per-request Basic auth

Besides Bearer tokens, the auth entity also accepts HTTP Basic credentials on any
request. The username is matched against the `identifier` field and the password is
verified against the stored hash, resolving the same principal a login would.

```bash
curl -u alice@example.com:s3cr3t http://localhost:8000/api/v1/my-collection
```

## Password Hashing

Passwords are hashed with PBKDF2-SHA256. The encoded value has the form
`pbkdf2$sha256$<rounds>$<salt>$<hash>` and is stored under `_auth.passwordHash`. The
raw password is never persisted. The iteration count defaults to 390000 and is
configurable via the `PASSWORD_HASH_ROUNDS` environment variable (the stored string
records the rounds it was hashed with, so changing the env var does not invalidate
existing hashes).

## Using the Token

Pass the token as a Bearer token on subsequent requests:

```bash
curl -H "Authorization: Bearer eyJ..." http://localhost:8000/api/v1/my-collection
```

## Environment Variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `JWT_SECRET` | `yaml-api-dev-secret-change-me` | HS256 signing key. The default is insecure -- set a strong random value in production. |
| `JWT_EXPIRATION_HOURS` | `24` | Token lifetime in hours. |
| `PASSWORD_HASH_ROUNDS` | `390000` | PBKDF2 iteration count for newly hashed passwords. |

## Examples

### Register, log in, and call a protected endpoint

```bash
# Register
curl -X POST http://localhost:8000/api/v1/users/register \
  -H 'Content-Type: application/json' \
  -d '{"email": "alice@example.com", "displayName": "Alice", "password": "s3cr3t"}'

# Login
curl -X POST http://localhost:8000/api/v1/users/login \
  -H 'Content-Type: application/json' \
  -d '{"email": "alice@example.com", "password": "s3cr3t"}'
# Returns: {"token": "eyJ...", "user": {...}}

# Use the token
curl -H "Authorization: Bearer eyJ..." http://localhost:8000/api/v1/my-collection
```

## Edge Cases

- **Password minimum length.** Enforced as non-empty only (min length 1). No
  complexity requirements exist.

- **Login with wrong password.** Returns 401 `{"detail": "Invalid credentials"}`. The
  message does NOT reveal whether the identifier or the password was wrong, which
  prevents user enumeration.

- **Login with non-existent identifier.** Returns the same 401. Indistinguishable
  from a wrong-password response.

- **Password in update payload.** A `password` sent on update or replace is re-hashed
  and `_auth.passwordHash` is updated. The raw value is not stored.

- **Password in response.** Never included. Read responses strip every
  underscore-prefixed key (so `_auth.passwordHash` is gone), and login additionally
  excludes the plain `password` from its `user` object.

- **JWT expiration.** Tokens expire after `JWT_EXPIRATION_HOURS` (default 24).

- **JWT decode failure.** An expired, malformed, or bad-signature token decodes to
  null. Authentication then falls through to other methods (API key, Basic); if none
  succeed the request is unauthenticated and a protected route returns 401.

## Errors

| Condition | HTTP / parse | Response |
|-----------|--------------|----------|
| Missing `identifier` or `password` on login | 401 | `{"detail": "Invalid credentials"}` |
| Wrong password on login | 401 | `{"detail": "Invalid credentials"}` |
| Non-existent identifier on login | 401 | `{"detail": "Invalid credentials"}` |
| Missing `password` on register | 422 | Pydantic validation error |
| Expired or invalid JWT on a protected route | 401 | `{"detail": "Unauthorized"}` |
| `password` field declared in `fields:` | parse `AUTH_PASSWORD_FIELD_FORBIDDEN` | "Password input is implicit when auth.via includes password" |
| `passwordHash` field declared in `fields:` | parse `AUTH_PASSWORD_HASH_FIELD_FORBIDDEN` | "passwordHash is implicit storage when auth.via includes password" |
| `auth.roles` names a missing field | parse `AUTH_ROLES_FIELD_NOT_FOUND` | "Roles field '<name>' not found in entity ..." |
| `auth.roles` names a non-enum field | parse `AUTH_ROLES_FIELD_NOT_ENUM` | "Roles field '<name>' must be of type 'enum'" |

## See Also

- [Authentication required by default](./auth-required-by-default.md)
- [Auth overview](./overview.md)
- [API key provider](./apikey-provider.md)
- [Login, SSO, and the token flow](./login-and-sso.md)
- [Roles overview](../roles/overview.md)
- [Access control](../controllers/access-control.md)
- [Environment variables](../configuration/environment-variables.md)
