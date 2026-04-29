---
title: "Auth Overview"
description: Declares an entity as an identity provider, enabling authentication, token issuance, and role-based access control.
---

Declares an entity as an identity provider, enabling authentication, token issuance, and role-based access control.

## Syntax

```yaml
entities:
  user:
    type: auth
    auth:
      identifier: email
      via: password
    roles:
      values: [admin, moderator, user]
      default: user
      hierarchy:
        admin: [moderator]
        moderator: [user]
    fields:
      id: { type: id }
      email: { type: string, required: true, unique: true }
      displayName: { type: string, required: true }
```

## Behavior

- **Parse time:** `type: auth` requires an `auth:` block. The `auth.identifier` and `auth.via` fields are validated. If a `roles:` block is present, its `values` and `default` are validated.
- **Compile time:** Register and login endpoints are generated (controlled by `api.operations.auth`). A `password` field is injected into the create model for password-based auth entities.
- **Runtime:** Principals authenticated via this entity receive a JWT with `sub` set to the primary key value. The entity participates in ABAC rules as `identity:entityName`.

## Options

### `type: auth`

Marks the entity as an identity provider. Only valid value: `"auth"`.

Effects:
- Generates `register` and `login` endpoints (controlled by `api.operations.auth`).
- Principals authenticated via this entity receive a JWT with `sub` set to the user's primary key value.
- The entity participates in ABAC rules as `identity:entityName`.

### `auth:` block

| Field | Required | Type | Description |
|-------|----------|------|-------------|
| `identifier` | yes | string (field name) | The field used as the login username. |
| `via` | yes | string or list of strings | Authentication methods: `"password"`, `"apiKey"`, or a list. |

### `roles:` block (entity-level)

| Field | Required | Type | Default | Description |
|-------|----------|------|---------|-------------|
| `values` | yes | list of strings | -- | All valid role names. |
| `default` | yes | string | -- | Role assigned on user creation. Must be in `values`. |
| `hierarchy` | no | map | none | Role inclusion relationships. See [roles hierarchy](../roles/hierarchy.md). |

## Internal Storage

Auth-related fields (password hashes, API keys, roles) are stored under a `_auth` namespace in MongoDB, not as flat top-level fields.

```
# MongoDB document (internal)
{ "id": "abc", "email": "alice@example.com", "_auth": { "passwordHash": "pbkdf2:..." } }

# principal.record (what access rules see)
{ "id": "abc", "email": "alice@example.com", "displayName": "Alice" }
```

The `principal.record` object returned by access rules contains only the entity's declared fields. Internal `_auth` fields, `password`, and `passwordHash` are stripped.

## Examples

### Single auth entity with password

```yaml
entities:
  user:
    type: auth
    auth:
      identifier: email
      via: password
    roles:
      values: [admin, moderator, user]
      default: user
      hierarchy:
        admin: [moderator]
        moderator: [user]
    fields:
      id: { type: id }
      email: { type: string, required: true, unique: true }
      displayName: { type: string, required: true }
```

### API key auth entity

```yaml
entities:
  apiClient:
    type: auth
    auth:
      identifier: clientId
      via: apiKey
    roles:
      values: [free, premium, enterprise]
      default: free
      hierarchy:
        enterprise: [premium]
        premium: [free]
    fields:
      id: { type: id }
      clientId: { type: string, required: true, unique: true }
      name: { type: string, required: true }
```

### Multiple auth entities

```yaml
entities:
  user:
    type: auth
    auth:
      identifier: email
      via: password
    roles:
      values: [admin, moderator, user]
      default: user
      hierarchy:
        admin: [moderator]
        moderator: [user]
    fields:
      email: { type: string, required: true, unique: true }

  apiClient:
    type: auth
    auth:
      identifier: clientId
      via: apiKey
    roles:
      values: [free, premium, enterprise]
      default: free
    fields:
      clientId: { type: string, required: true, unique: true }
```

With multiple auth entities, access rules must use the entity prefix:

```yaml
access: user:admin           # required -- unscoped "admin" is a parse error
access: apiClient:enterprise
```

## Edge Cases

- **Multiple auth entities: Bearer token resolution.** When multiple auth entities exist, Bearer token resolution tries each identity collection in order. The first match wins.

- **Multiple auth entities: scoped syntax required.** Access rules must use scoped syntax (`user:admin`, not just `admin`). An unscoped role name is a parse error (`ACCESS_AMBIGUOUS_ROLE`) when multiple auth entities exist.

- **Single auth entity: scoped and unscoped both work.** With a single auth entity, both `admin` and `user:admin` are valid in access rules.

- **`identifier` field should have `unique: true`.** If the identifier field is not unique, login may match the wrong user (first found). No parse error is raised, but this is a configuration mistake.

- **Password is never stored.** Only `_auth.passwordHash` is persisted. The hash uses PBKDF2-SHA256 with 390,000 iterations.

- **API key storage.** The API key is stored in `_auth.apiKey`. It must be provided by the client on creation; there is no auto-generation mechanism.

- **Entity without `roles:` section.** The entity still authenticates principals but has no role-based access control. `access: "*"` and `access: user:*` still work. `access: user:admin` will never match because no roles are defined.

## Errors

| Condition | Error code | Message |
|-----------|-----------|---------|
| `type: auth` without `auth:` block | schema validation | `auth` is required when type is "auth" |
| `password` declared in `fields:` | `AUTH_PASSWORD_FIELD_FORBIDDEN` | "Password input is implicit when auth.via includes password" |
| `passwordHash` declared in `fields:` | `AUTH_PASSWORD_HASH_FIELD_FORBIDDEN` | "passwordHash is implicit storage when auth.via includes password" |
| Unscoped role with multiple auth entities | `ACCESS_AMBIGUOUS_ROLE` | "Unscoped role 'X' is ambiguous with multiple auth entities" |

## See Also

- [Password provider](./password-provider.md)
- [API key provider](./apikey-provider.md)
- [Claim mapping](./claim-mapping.md)
- [Roles overview](../roles/overview.md)
- [Access control](../controllers/access-control.md)
