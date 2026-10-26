---
title: "Role Hierarchy"
description: Declares which roles include other roles, so a rule for a lower role also admits the roles above it.
---

Role hierarchy lets a higher role include lower ones (for example `admin` including
`moderator`). You declare it in the `roles:` block of a `type: auth` entity.

## Syntax

```yaml
version: "0.2"

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
```

Each key of `hierarchy` is a role; its value lists the roles that role includes.

## Behavior

- **Parse time:** every role named in `hierarchy`, as a key or in a list, must be one
  of `values` (`ROLES_HIERARCHY_UNKNOWN_ROLE`), and the inclusions must not form a
  cycle (`ROLES_HIERARCHY_CYCLE`). A `roles:` block is accepted only on a
  `type: auth` entity.
- **Generation:** the hierarchy is flattened transitively. Given `admin: [moderator]`
  and `moderator: [user]`:
  - `admin` -> `{moderator, user}`
  - `moderator` -> `{user}`
- **Enforcement:** a principal holds its own roles plus every role they include. An
  `admin` therefore satisfies `access: user:moderator` and `access: user:user`. The
  same expansion decides which roles a caller may grant (see
  [Roles overview](./overview.md#storage)).

> **Enforcement**
>
> Roles, role hierarchies, `<entity>:*` scoping, and ownership/ABAC `when` rules
> are enforced by the generated FastAPI backend, the generated DRF backend, and the
> `stackform run` dev server alike. A request that no rule admits gets 401 when it
> carries no valid credentials and 403 otherwise; a missing record answers 404
> before ownership is checked.

## Options

| Field | Required | Type | Description |
|-------|----------|------|-------------|
| `roles.hierarchy` | no | map of role to list of roles | Each key is a role; the value lists the roles it includes. |

## Examples

### Gating by the lowest role that may act

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
    roles:
      values: [admin, moderator, user]
      default: user
      hierarchy:
        admin: [moderator]
        moderator: [user]
    fields:
      id: { type: id }
      email: { type: string, required: true, unique: true }

  post:
    fields:
      id: { type: id }
      title: { type: string, required: true }

repositories:
  users:
    entity: user
  posts:
    entity: post

services:
  posts:
    repository: posts

controllers:
  posts:
    service: posts
    operations:
      list: { access: public }
      get: { access: public }
      create: { access: user:user }
      update: { access: user:moderator }
      delete: { access: user:admin }
```

A `moderator` can create and update posts but not delete them; an `admin` can do
all three. Each rule names the lowest role allowed, and the hierarchy admits every
role above it.

### Multiple auth entities

```yaml
entities:
  user:
    type: auth
    auth: { identifier: email, via: password }
    roles:
      values: [admin, moderator, user]
      default: user
      hierarchy:
        admin: [moderator]
        moderator: [user]
    fields:
      id: { type: id }
      email: { type: string, required: true, unique: true }
  apiClient:
    type: auth
    auth: { identifier: clientId, via: apiKey }
    roles:
      values: [enterprise, premium, free]
      default: free
      hierarchy:
        enterprise: [premium]
        premium: [free]
    fields:
      id: { type: id }
      clientId: { type: string, required: true, unique: true }
      apiKey: { type: string, required: true }
```

Hierarchies are scoped per entity: `user` roles and `apiClient` roles are
independent, and one entity's role never includes another entity's role.

### No hierarchy

Omit `hierarchy`. Each role then matches only itself.

## Errors

| Condition | Error code | Message |
|-----------|-----------|---------|
| `hierarchy` names a role missing from `values` | `ROLES_HIERARCHY_UNKNOWN_ROLE` | Role hierarchy references undeclared role '<role>' |
| `hierarchy` is cyclic | `ROLES_HIERARCHY_CYCLE` | Role hierarchy for '<entity>' is cyclic through '<role>' |
| `roles:` on an entity that is not `type: auth` | `SCHEMA_VALIDATION_ERROR` | |

## See Also

- [Roles overview](./overview.md)
- [Access control](../controllers/access-control.md)
- [Auth overview](../auth/overview.md)
