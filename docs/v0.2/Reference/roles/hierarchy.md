---
title: "Role Hierarchy"
description: Defines which roles subsume other roles, so that a principal with a higher role automatically satisfies access checks for lower roles.
---

Defines which roles subsume other roles, so that a principal with a higher role automatically satisfies access checks for lower roles.

## Syntax

The `hierarchy` map is declared inside the entity-level `roles:` block.

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
```

Each key in `hierarchy` is a role name. The value is a list of roles that the key role includes (subsumes).

## Behavior

- **Parse time:** All hierarchy keys and included roles are validated against `roles.values`.
- **Runtime (role expansion):** Inclusion is expanded transitively. Given `admin: [moderator]` and `moderator: [user]`, the engine computes:
  - `admin` -> `{moderator, user}`
  - `moderator` -> `{user}`

When an access rule requires role X, a principal with role Y passes if X is in Y's expanded set (or X equals Y).

## Options

| Field | Required | Type | Description |
|-------|----------|------|-------------|
| `hierarchy` | no | map of string to list of strings | Each key is a role; the value is the list of roles it includes. |

## Access Rule Matching

| Principal role | `access: user` | `access: moderator` | `access: admin` |
|---------------|:-:|:-:|:-:|
| `user` | pass | fail | fail |
| `moderator` | pass | pass | fail |
| `admin` | pass | pass | pass |

## Examples

### Standard three-tier hierarchy

```yaml
roles:
  values: [admin, moderator, user]
  default: user
  hierarchy:
    admin: [moderator]
    moderator: [user]
```

- `admin` includes `moderator`, which includes `user`.
- `admin` effectively has `{admin, moderator, user}`.
- `moderator` effectively has `{moderator, user}`.
- `user` has only `{user}`.

### Tiered API access

```yaml
roles:
  values: [free, premium, enterprise]
  default: free
  hierarchy:
    enterprise: [premium]
    premium: [free]
```

| Client tier | `access: apiClient:free` | `access: apiClient:premium` | `access: apiClient:enterprise` |
|------------|:-:|:-:|:-:|
| `free` | pass | fail | fail |
| `premium` | pass | pass | fail |
| `enterprise` | pass | pass | pass |

### Flat roles (no hierarchy)

```yaml
roles:
  values: [free, pro, enterprise]
  default: free
```

No `hierarchy:` key. Each role matches only itself. `access: enterprise` matches only `enterprise`.

## Edge Cases

- **Transitive expansion.** `admin: [moderator], moderator: [user]` means `admin` effectively includes `{moderator, user}`. The expansion is computed recursively at startup.

- **Role not in hierarchy but in `values`.** A role that appears in `values` but not as a key in `hierarchy` is a leaf role. It only matches itself.

- **Hierarchy with no entries.** An empty `hierarchy: {}` or omitting `hierarchy` entirely is equivalent to flat roles with no inclusion.

- **`access: user` with hierarchy above.** If `moderator: [user]` and `admin: [moderator]`, then `access: user` matches principals with role `user`, `moderator`, or `admin` -- anyone who transitively includes `user`.

- **No cross-entity inheritance.** Role hierarchy is strictly per-entity. `user:admin` and `apiClient:admin` are completely independent. There is no mechanism to declare that one entity's role includes another entity's role.

- **Circular hierarchy.** Cycles (e.g., `admin: [user], user: [admin]`) are NOT detected at parse time. They will cause infinite recursion during role expansion at runtime.

**Warning:** Always ensure hierarchy definitions form a directed acyclic graph. Circular references are a known limitation that will cause runtime failures.

## Errors

| Condition | Error code | Message |
|-----------|-----------|---------|
| Hierarchy key not in `values` | `ROLES_HIERARCHY_KEY_INVALID` | Key must be a declared role value |
| Included role not in `values` | `ROLES_HIERARCHY_VALUE_INVALID` | Included role must be a declared role value |

## See Also

- [Roles overview](./overview.md)
- [Access control](../controllers/access-control.md)
- [Auth overview](../auth/overview.md)
