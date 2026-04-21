---
title: "Reference: Password Provider"
description: Enables username/password authentication with secure hashing for an auth entity.
---

Enables username/password authentication with secure hashing for an auth entity.

## Syntax

```yaml
entities:
  user:
    type: auth
    auth:
      identifier: email
      via: password
    fields:
      id: { type: id }
      email: { type: string, required: true, unique: true }
      displayName: { type: string, required: true }
```

## Behavior

- **Parse time:** The `password` provider is validated. The `identifier` field must exist in `fields:`. Declaring a `password` or `passwordHash` field in `fields:` raises a parse error -- these are implicit.
- **Compile time:** A `password` field (type: string, required, min_length: 1) is injected into the create Pydantic model. Register and login endpoints are generated.
- **Runtime:** On register, the password is hashed and stored under `_auth.passwordHash`. On login, the password is verified against the stored hash and a JWT is issued on success.

## Options

| Field | Required | Type | Description |
|-------|----------|------|-------------|
| `identifier` | yes | string (field name) | The field used as the login username. Must be declared in `fields:`. |

The `identifier` field should have `unique: true`. Common values: `email`, `username`.

## Generated Endpoints

With `register` and `login` enabled (the default), the engine generates:

| Method | Path | Description |
|--------|------|-------------|
| POST | `/{base_path}/register` | Create a new user with hashed password |
| POST | `/{base_path}/login` | Authenticate and receive a JWT |

## Register Request

The `password` field is injected into the register payload automatically. It is not declared in `fields:`.

```json
POST /users/register
{
  "email": "alice@example.com",
  "displayName": "Alice",
  "password": "s3cr3t"
}
```

Returns the created user record without the password hash.

## Login Request

```json
POST /users/login
{
  "email": "alice@example.com",
  "password": "s3cr3t"
}
```

Returns:

```json
{
  "token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
}
```

## Token Format

The JWT payload contains:

```json
{
  "sub": "<primary key value>",
  "identity_collection": "<collection name>",
  "iat": 1700000000,
  "exp": 1700086400
}
```

- `sub` is the user's primary key value (the `idField` value, NOT the identifier field). Downstream access rules reference it as `principal.sub`.
- `identity_collection` identifies which auth entity the principal belongs to.

## Password Hashing

Passwords are hashed with PBKDF2-SHA256 at 390,000 iterations. The hash is stored under `_auth.passwordHash` in MongoDB. The raw password is never persisted.

## Using the Token

Pass the token as a Bearer token on subsequent requests:

```bash
curl -H "Authorization: Bearer eyJ..." http://localhost:8000/notes
```

## Examples

### Register and use a protected endpoint

```bash
# Register
curl -X POST http://localhost:8000/users/register \
  -H 'Content-Type: application/json' \
  -d '{"email": "alice@example.com", "displayName": "Alice", "password": "s3cr3t"}'

# Login
curl -X POST http://localhost:8000/users/login \
  -H 'Content-Type: application/json' \
  -d '{"email": "alice@example.com", "password": "s3cr3t"}'
# Returns: {"token": "eyJ..."}

# Use token
curl -H "Authorization: Bearer eyJ..." http://localhost:8000/notes
```

## Edge Cases

- **Password minimum length.** No minimum length is enforced beyond non-empty (min_length: 1). No complexity requirements exist.

- **Login with wrong password.** Returns 401 Unauthorized. The error message does NOT reveal whether the identifier or the password was wrong. This prevents user enumeration attacks.

- **Login with non-existent identifier.** Returns the same 401 Unauthorized. Indistinguishable from a wrong password response.

- **Password in update payload.** If a password field is sent in an update request, the password is re-hashed and `_auth.passwordHash` is updated.

- **Password in response.** NEVER included. The `password` and `passwordHash` fields are stripped from all responses.

- **JWT expiration.** Tokens expire after 24 hours by default. Configurable via the `JWT_EXPIRATION_HOURS` environment variable.

- **JWT signing.** HS256 algorithm, signed with the `JWT_SECRET` environment variable.

**Warning:** The default `JWT_SECRET` is `"yaml-api-dev-secret-change-me"`. This is insecure. Always set `JWT_SECRET` to a strong random value in production.

- **JWT decode failure.** If the Bearer token is not a valid JWT (expired, bad signature, malformed), it returns `null` from the decoder. The authentication step then falls through to other auth methods (e.g., API key). If no method succeeds, the request is unauthenticated.

## Errors

| Condition | HTTP Status | Response |
|-----------|-------------|----------|
| Missing `password` in register payload | 422 | Pydantic validation error |
| Wrong password on login | 401 | Unauthorized |
| Non-existent identifier on login | 401 | Unauthorized |
| Expired JWT token | 401 | Unauthorized (on protected routes) |
| `password` field declared in `fields:` | parse error `AUTH_PASSWORD_FIELD_FORBIDDEN` | "Password input is implicit" |
| `passwordHash` field declared in `fields:` | parse error `AUTH_PASSWORD_HASH_FIELD_FORBIDDEN` | "passwordHash is implicit storage" |

## See Also

- [Auth overview](./overview.md)
- [API key provider](./apikey-provider.md)
- [Access control](../controllers/access-control.md)
- [Environment variables](../configuration/environment-variables.md)
