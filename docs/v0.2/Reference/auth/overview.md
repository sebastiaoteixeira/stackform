---
title: "Auth Overview"
description: Declares an entity as an identity provider, enabling authentication, token issuance, and role-based access control.
---

Declares an entity as an identity provider, enabling authentication, token issuance, and role-based access control.

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
  user:
    type: auth
    auth:
      identifier: email
      via: password
      roles: role
    fields:
      id: { type: id }
      email: { type: string, required: true, unique: true }
      displayName: { type: string, required: true }
      role:
        type: enum
        values: [admin, moderator, user]
        default: user
```

Roles are an ordinary `enum` field named by `auth.roles`. The role's allowed values
and the default assigned on create come from that field's `values:` and `default:`.

> **Note:** A standalone entity-level `roles: { values, default, hierarchy }` block is
> NOT wired in v0.2 and is silently ignored. Use `auth.roles: <enumFieldName>` pointing
> at an `enum` field. Role hierarchy is covered under "Role hierarchy" below.

## Behavior

- **Parse time:** declaring `type: auth` requires an `auth:` block (schema validation).
  The `auth.identifier` and `auth.via` keys are optional in the JSON schema, but a
  password or API-key provider cannot resolve a principal without them, so treat them
  as effectively required. If `auth.roles` is set, the named field must exist
  (`AUTH_ROLES_FIELD_NOT_FOUND`) and be of `type: enum` (`AUTH_ROLES_FIELD_NOT_ENUM`).
- **Compile time:** register and login endpoints are generated only when enabled via
  `api.operations.auth: { register: true, login: true }` (off by default). For
  password-based auth, a `password` input is injected into the create model.
- **Runtime:** principals authenticated via this entity receive a JWT whose `sub` is the
  identity record's primary-key value. The entity participates in access rules as
  `<entityName>:*` and `<entityName>:<role>`.

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

## Options

### `type: auth`

Marks the entity as an identity provider. Only valid value: `"auth"`. The default for
any entity is `base`.

Effects:
- Generates `register` and `login` endpoints when `api.operations.auth` enables them.
- Principals authenticated via this entity receive a JWT with `sub` set to the record's
  primary-key value.
- The entity participates in access rules as `<entityName>:*` and
  `<entityName>:<role>`.

### `auth:` block

| Field | Required | Type | Description |
|-------|----------|------|-------------|
| `identifier` | effectively yes | string (field name) | The field used as the login username (for password) or matched value. Not schema-enforced, but auth cannot resolve a principal without it. |
| `via` | effectively yes | string, list of strings, or list of objects | Built-in methods (`"password"`, `"apiKey"`) as strings, and/or inline provider bindings as objects (see below). |
| `roles` | no | string (field name) | Names an `enum` field that holds the principal's role. See [roles overview](../roles/overview.md). |
| `bindings` | no | list of objects | External identity providers (OIDC/SAML). Each entry sets `provider`, `identifier`, optional `claim_mapping` and `auto_provision`. See [claim mapping](./claim-mapping.md). |

`via` accepts plain strings for the built-in `password` and `apiKey` methods. A list
entry may instead be an object that declares an external provider binding inline,
equivalent to adding the same entry under `auth.bindings`. Each object takes:

| Key | Required | Type | Description |
|-----|----------|------|-------------|
| `provider` | yes | string | Name of the configured external provider (OIDC/SAML). |
| `identifier` | no | string (field name) | Field matched against the provider's principal. Defaults to `auth.identifier`. |
| `claim_mapping` | no | map (string → string) | Maps provider claims onto entity fields. See [claim mapping](./claim-mapping.md). |
| `auto_provision` | no | boolean | Create a local record on first login when no match exists. Defaults to `true`. |

Bindings declared in `via` are merged with any under `auth.bindings`; a `via` binding
wins if both name the same `provider`.

```yaml
entities:
  user:
    type: auth
    auth:
      identifier: email
      via:
        - password
        - provider: google
          identifier: email
          claim_mapping: { email: email, name: displayName }
          auto_provision: true
      roles: role
```

### Role hierarchy

A role hierarchy can be declared in a top-level `roles:` map keyed by entity name:

```yaml
roles:
  user:
    admin: [moderator]
    moderator: [user]
```

This is parsed and reaches the generated React UI's RBAC matrix, but it is NOT applied
during backend access enforcement: a principal with role `admin` does NOT inherit
`moderator`'s permissions. Only exact role matches are checked today. See
[roles hierarchy](../roles/hierarchy.md).

## How a request is authenticated

The generated backend resolves a principal by trying credentials in this order:

1. **Bearer JWT** (`Authorization: Bearer <jwt>`) -- used for password-based entities.
   The token carries only `sub` and `identity_collection`; the identity record and its
   roles are loaded from MongoDB on every request, so role changes apply immediately.
2. **API key** (`X-API-Key: <key>`, or `Authorization: Bearer <key>`) -- matched against
   the top-level `apiKey` field of each `apiKey` entity.
3. **HTTP Basic** (`Authorization: Basic <base64(identifier:password)>`) -- the identifier
   is matched against the `auth.identifier` field and the password verified against the
   stored hash.

The resolved principal exposes:
- `principal.sub` -- the primary-key value of the matched record.
- `principal.identity_collection` -- the entity/collection that matched.
- `principal.roles` -- read from the `auth.roles` enum field (falling back to a `roles`
  or `role` field if `auth.roles` is unset).
- `principal.record` -- the matched record. Stored fields are referenced in `when` rules
  as `principal.record.<field>`. In the generated FastAPI/DRF backends this is the raw
  MongoDB document (including the internal `_auth` namespace); the `yaml-api run` dev
  server passes a sanitized record.

## Internal Storage

For password auth, the password is never stored; only the hash is persisted under an
internal `_auth` namespace. The hash format is
`pbkdf2$sha256$<rounds>$<salt>$<hash>` (PBKDF2-HMAC-SHA256, default 390000 rounds,
configurable via `PASSWORD_HASH_ROUNDS`).

Roles are NOT stored under `_auth` -- they live in the declared `enum` field and are read
from there at request time.

```
# MongoDB document (internal)
{ "id": "abc", "email": "alice@example.com", "role": "admin",
  "_auth": { "passwordHash": "pbkdf2$sha256$390000$..." } }
```

The login response and the `principal.record` seen by the `run` dev server strip
`password`, `_id`, and `_auth`. In the generated FastAPI/DRF backends, `principal.record`
is the raw document; do not rely on access rules to hide `_auth` there.

## Environment variables

| Variable | Default | Effect |
|----------|---------|--------|
| `JWT_SECRET` | dev placeholder | HS256 signing secret for issued tokens. Set a strong value in production. |
| `JWT_EXPIRATION_HOURS` | `24` | Token lifetime in hours. |
| `PASSWORD_HASH_ROUNDS` | `390000` | PBKDF2-SHA256 iteration count for password hashing. |

## Examples

### Single auth entity with password and roles

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
  user:
    type: auth
    auth:
      identifier: email
      via: password
      roles: role
    fields:
      id: { type: id }
      email: { type: string, required: true, unique: true }
      displayName: { type: string, required: true }
      role:
        type: enum
        values: [admin, moderator, user]
        default: user
```

Login: `POST /api/v1/users/login` returns `{"token": "...", "user": {...}}` (the user
excludes `password`, `_id`, and `_auth`).

### API key auth entity

The API key is a plain top-level `apiKey` string field; it is matched verbatim at request
time. There is no auto-generation -- the client supplies the key on creation.

```yaml
version: "0.2"

api:
  basePath: /api
  version: v1

entities:
  apiClient:
    type: auth
    auth:
      identifier: clientId
      via: apiKey
      roles: tier
    fields:
      id: { type: id }
      clientId: { type: string, required: true, unique: true }
      apiKey: { type: string, required: true }
      name: { type: string, required: true }
      tier:
        type: enum
        values: [free, premium, enterprise]
        default: free
```

> **Security:** `apiKey` is an ordinary field and is returned in CRUD responses; restrict
> read access to this entity. See [API key provider](./apikey-provider.md).

### Multiple auth entities

```yaml
version: "0.2"

api:
  basePath: /api
  version: v1

entities:
  user:
    type: auth
    auth:
      identifier: email
      via: password
      roles: role
    fields:
      id: { type: id }
      email: { type: string, required: true, unique: true }
      role:
        type: enum
        values: [admin, moderator, user]
        default: user

  apiClient:
    type: auth
    auth:
      identifier: clientId
      via: apiKey
    fields:
      id: { type: id }
      clientId: { type: string, required: true, unique: true }
      apiKey: { type: string, required: true }
```

With multiple auth entities, role-bearing access rules must use the entity prefix:

```yaml
access: user:admin           # required -- unscoped "admin" is a parse error
access: apiClient:enterprise
```

## Edge Cases

- **Multiple auth entities: Bearer token resolution.** When multiple auth entities exist,
  the JWT carries its `identity_collection`, so resolution targets that collection
  directly. API-key and Basic credentials are tried against each entity in turn; the first
  match wins.

- **Multiple auth entities: scoped syntax required.** Role access rules must use scoped
  syntax (`user:admin`, not just `admin`). An unscoped role name is a parse error
  (`ACCESS_AMBIGUOUS_ROLE`) when more than one auth entity exists.

- **Single auth entity: scoped and unscoped both work.** With a single auth entity, both
  `admin` and `user:admin` are valid in access rules.

- **`identifier` field should have `unique: true`.** If the identifier field is not unique,
  login may match the wrong record (first found). No parse error is raised, but this is a
  configuration mistake.

- **Password is never stored.** Only `_auth.passwordHash` is persisted, using
  PBKDF2-SHA256 with 390000 iterations by default.

- **Entity without `auth.roles`.** The entity still authenticates principals but has no
  roles. `access: public`, `access: "*"`, and `access: user:*` still work;
  `access: user:admin` will never match because no role values exist.

## Errors

| Condition | Error code | Message |
|-----------|-----------|---------|
| `type: auth` without `auth:` block | schema validation | `auth` is required when type is "auth" |
| `auth.roles` names a missing field | `AUTH_ROLES_FIELD_NOT_FOUND` | "Roles field 'X' not found in entity 'Y'" |
| `auth.roles` field is not an enum | `AUTH_ROLES_FIELD_NOT_ENUM` | "Roles field 'X' must be of type 'enum'" |
| `password` declared in `fields:` | `AUTH_PASSWORD_FIELD_FORBIDDEN` | "Password input is implicit when auth.via includes password" |
| `passwordHash` declared in `fields:` | `AUTH_PASSWORD_HASH_FIELD_FORBIDDEN` | "passwordHash is implicit storage when auth.via includes password" |
| Unscoped role with multiple auth entities | `ACCESS_AMBIGUOUS_ROLE` | "Unscoped role 'X' is ambiguous with multiple auth entities; use 'entity:X'" |
| Role used with no auth entity | `ACCESS_NO_AUTH_ENTITY` | "Cannot use role 'X' without auth entities" |

## See Also

- [Password provider](./password-provider.md)
- [API key provider](./apikey-provider.md)
- [Claim mapping](./claim-mapping.md)
- [Roles overview](../roles/overview.md)
- [Roles hierarchy](../roles/hierarchy.md)
- [Access control](../controllers/access-control.md)
