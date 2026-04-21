---
title: "Reference: Roles Overview"
description: Declares per-entity roles with valid values, a default, and an optional hierarchy for role-based access control.
---

# Reference: Roles Overview

Declares per-entity roles with valid values, a default, and an optional hierarchy for role-based access control.

## Syntax

Roles are declared at the entity level inside the `roles:` block on `type: auth` entities.

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
      displayName: { type: string, required: true }
```

Roles are NOT a field. There is no `role` enum field on the entity. The `roles:` block is a standalone authorization concept.

## Behavior

- **Parse time:** `roles.values` is validated. `roles.default` must be in `values`. All hierarchy keys and included roles must be in `values`.
- **Compile time:** No role field appears in Pydantic models. The default role is injected into `_auth.roles` on user creation.
- **Runtime:** The principal's role is read from `_auth.roles` in MongoDB. Role-based access rules match against this value, expanding hierarchy transitively.

## Storage

Roles are stored in the `_auth` namespace in MongoDB, alongside `passwordHash`:

```json
{
  "id": "abc-123",
  "email": "admin@example.com",
  "displayName": "Admin",
  "_auth": {
    "passwordHash": "pbkdf2$sha256$390000$...",
    "roles": "admin"
  }
}
```

The `_auth` namespace is stripped from API responses. Roles are NOT exposed in CRUD responses and NOT writable via create/update payloads.

## Options

| Field | Required | Type | Default | Description |
|-------|----------|------|---------|-------------|
| `values` | yes | list of strings | -- | All valid role names for this entity. |
| `default` | yes | string | -- | Role assigned automatically on user creation. Must be in `values`. |
| `hierarchy` | no | map of string to list | none | Role inclusion relationships. See [hierarchy](./hierarchy.md). |

## Examples

### Flat roles (no hierarchy)

```yaml
entities:
  user:
    type: auth
    auth:
      identifier: email
      via: password
    roles:
      values: [free, pro, enterprise]
      default: free
    fields:
      email: { type: string, required: true, unique: true }
```

With no `hierarchy:` declared, each role matches only itself. `access: enterprise` matches only principals with role `enterprise`, not `pro` or `free`.

### Roles with hierarchy

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
        admin: [moderator]    # admin users inherit moderator permissions
        moderator: [user]     # moderator users inherit user permissions
    fields:
      email: { type: string, required: true, unique: true }
```

The hierarchy flows from higher privilege to lower:

```text
admin  (highest privilege)
  includes moderator
    includes user  (lowest privilege)
```

- `admin` includes `moderator`, which includes `user`.
- `access: moderator` matches both `moderator` and `admin`.
- `access: user` matches `user`, `moderator`, and `admin`.

### Multiple auth entities with separate roles

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
      hierarchy:
        enterprise: [premium]
        premium: [free]
    fields:
      clientId: { type: string, required: true, unique: true }
```

Role names are scoped to their entity. `user:admin` and `apiClient:enterprise` are independent.

## Edge Cases

- **`default` must be in `values`.** If `default` is not one of the declared `values`, the parser raises `ROLES_DEFAULT_NOT_IN_VALUES`.

- **Hierarchy keys must be in `values`.** If a key in `hierarchy` is not in `values`, the parser raises `ROLES_HIERARCHY_KEY_INVALID`.

- **Hierarchy included roles must be in `values`.** If a role listed in a hierarchy value is not in `values`, the parser raises `ROLES_HIERARCHY_VALUE_INVALID`.

- **Circular hierarchy.** Circular references (e.g., `admin: [user], user: [admin]`) are NOT detected at parse time. They will cause infinite recursion at runtime during role expansion.

**Warning:** Circular role hierarchies are a known limitation. Always ensure hierarchy definitions form a directed acyclic graph (DAG).

- **Roles stored in `_auth.roles`.** The role value is stored under `_auth.roles` in MongoDB. It is NOT a regular field and NOT writable via standard CRUD endpoints.

- **Default role on creation.** The default role is set automatically when a user registers. There is no way to set a different initial role via the API.

- **Role assignment.** There is currently no built-in endpoint for changing a user's role. Role changes must be done via direct MongoDB update or a custom service handler.

**Note:** This is a known limitation. A future version may add role management endpoints.

- **`roles:` on non-auth entity.** The `roles:` block is only valid on entities with `type: auth`. Declaring it on a regular entity raises `ROLES_ON_NON_AUTH_ENTITY`.

- **Entity without `roles:` section.** Users have no roles. Role-based access rules (e.g., `access: user:admin`) will never match for that entity's principals.

- **Single role per user.** Each user has exactly one role (stored as a string, not an array). Access rule matching treats it as a set of one, then expands via hierarchy.

## Errors

| Condition | Error code | Message |
|-----------|-----------|---------|
| `default` not in `values` | `ROLES_DEFAULT_NOT_IN_VALUES` | Default role must be in values |
| Hierarchy key not in `values` | `ROLES_HIERARCHY_KEY_INVALID` | Hierarchy key must be in values |
| Hierarchy included role not in `values` | `ROLES_HIERARCHY_VALUE_INVALID` | Included role must be in values |
| `roles:` on non-auth entity | `ROLES_ON_NON_AUTH_ENTITY` | Roles only valid on auth entities |

## See Also

- [Role hierarchy](./hierarchy.md)
- [Auth overview](../auth/overview.md)
- [Access control](../controllers/access-control.md)
