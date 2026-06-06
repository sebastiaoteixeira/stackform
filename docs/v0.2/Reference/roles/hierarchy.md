---
title: "Role Hierarchy"
description: Declares which roles subsume other roles. Parsed today but not yet applied during access enforcement; only the generated UI consumes it.
---

Role hierarchy lets a higher role subsume lower ones (for example `admin` including `moderator`). You declare it in the top-level `roles:` map, keyed by auth-entity name.

> **Current status**
>
> Role hierarchy is parsed and validated, but it is NOT applied when the generated
> backend evaluates access rules. Today only exact role matches are enforced, so a
> principal whose role is `admin` does NOT automatically satisfy `access: user:moderator`.
> The one consumer of the hierarchy is the generated React UI, which uses it to build
> its client-side role matrix. To gate routes by role today, use `auth.roles: <enumField>`
> and explicit `access: entity:role` rules (see "What works today" below).

## Syntax

The hierarchy lives in a top-level `roles:` map. Each top-level key is the name of a
`type: auth` entity; its value is a map of role to the list of roles that role includes.

```yaml
version: "0.2"

entities:
  user:
    type: auth
    auth:
      identifier: email
      via: password
      roles: role
    fields:
      email: { type: string, required: true, unique: true }
      role:
        type: enum
        values: [admin, moderator, user]
        default: user

roles:
  user:
    admin: [moderator]
    moderator: [user]
```

The `roles:` block is NOT placed inside the entity. It is a top-level section, and its
keys must name auth entities. A `roles:` key under an entity definition is silently
ignored by the v0.2 parser.

## Behavior

- **Parse time:** Each top-level key must name a declared `type: auth` entity, otherwise
  `ROLES_UNKNOWN_ENTITY` is raised. The role names inside the map are NOT checked against
  the enum field's `values`; unknown role names are accepted as-is.
- **Generation:** The hierarchy is flattened transitively and handed to the React UI
  generator. Given `admin: [moderator]` and `moderator: [user]`, the UI sees:
  - `admin` -> `{moderator, user}`
  - `moderator` -> `{user}`
- **Enforcement:** The generated backend does NOT apply this expansion. Access rules
  match the principal's role by exact string only.

> **Enforcement status**
>
> Roles (exact match), `identity:<entity>` scoping, and ownership/ABAC `when` rules
> are enforced by the generated FastAPI backend, the generated DRF backend, and the
> `yaml-api run` dev server alike. A request that fails a rule gets 401 (missing or
> invalid credentials), 403 (authenticated but not allowed), or 404 (record not
> found, checked before ownership). Two current limitations: role hierarchy (for
> example `admin` inheriting `moderator`) is accepted in YAML but not yet applied
> during enforcement -- only exact role matches are checked; and conditional or
> ownership rules require a v0.2 spec, because v0.1 specs do not parse `when` rules.

## Options

| Field | Required | Type | Description |
|-------|----------|------|-------------|
| `roles.<entity>` | no | map of role to list of roles | Each key is a role; the value lists the roles it includes. The entity name must be a declared `type: auth` entity. |

## What works today

Role checks are enforced through exact matching, with no inheritance. To make a role
gate work, declare the role as an `enum` field, point `auth.roles` at it, and write
explicit `access` rules per controller or operation.

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
      email: { type: string, required: true, unique: true }
      role:
        type: enum
        values: [admin, moderator, user]
        default: user

controllers:
  myCollection:
    access: user:admin   # only principals whose role field equals "admin"
```

With this spec, `DELETE /api/v1/my-collection/{id}` requires a `user` principal whose `role`
field is exactly `admin`. A `moderator` is rejected with 403, even if you declared a
hierarchy: hierarchy does not grant the `admin` role to a `moderator`.

The access value vocabulary that role gating relies on:

- `entity:role` -- principal of that auth entity whose role field equals `role` (exact).
- `entity:*` -- any authenticated principal of that auth entity, regardless of role.
- A bare `role` -- shorthand for `entity:role` when exactly one auth entity exists.
  With two or more auth entities, a bare role is `ACCESS_AMBIGUOUS_ROLE`; with none,
  it is `ACCESS_NO_AUTH_ENTITY`.

The principal's role is read at request time from the record's `auth.roles` enum field
(falling back to a `roles` or `role` field if `auth.roles` is unset). Role changes in
MongoDB take effect on the next request; the JWT does not carry roles.

## Examples

### Declaring a hierarchy (UI-only today)

```yaml
roles:
  user:
    admin: [moderator]
    moderator: [user]
```

- The generated React UI treats `admin` as including `{moderator, user}` for its
  client-side role matrix.
- The generated backend still matches `access: user:moderator` only against principals
  whose role field equals `moderator`. An `admin` principal is NOT auto-matched.

### Multiple auth entities

```yaml
roles:
  user:
    admin: [moderator]
    moderator: [user]
  apiClient:
    enterprise: [premium]
    premium: [free]
```

Each top-level key names a separate auth entity. Hierarchies are scoped per entity;
`user` roles and `apiClient` roles are independent. There is no mechanism to declare
that one entity's role includes another entity's role.

### No hierarchy

Omit the `roles:` block entirely (or list no inclusions). Roles then match only
themselves -- which, today, is the only behavior the backend enforces regardless.

## Errors

| Condition | Error code | Message |
|-----------|-----------|---------|
| Top-level `roles:` key is not a declared auth entity | `ROLES_UNKNOWN_ENTITY` | Role hierarchy references unknown auth entity '<name>' |

The role names listed inside the map are not validated against the enum field's
`values`, so a typo in a role name produces no error -- it simply never matches.

## See Also

- [Roles overview](./overview.md)
- [Access control](../controllers/access-control.md)
- [Auth overview](../auth/overview.md)
