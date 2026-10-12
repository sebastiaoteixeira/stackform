---
title: "Roles Overview"
description: Declare per-user roles with an enum field and wire them to authorization via auth.roles.
---

A role is an enum field on a `type: auth` entity, pointed at by `auth.roles`. The
field's value is read on every request and used to match role-scoped access rules
such as `access: user:admin`.

> **Enforcement status**
>
> Roles (exact match), `<entity>:*` scoping, and ownership/ABAC `when` rules
> are enforced by the generated FastAPI backend, the generated DRF backend, and the
> `stackform run` dev server alike. A request that fails a rule gets 401 (missing or
> invalid credentials), 403 (authenticated but not allowed), or 404 (record not
> found, checked before ownership). Two current limitations: role hierarchy (for
> example `admin` inheriting `moderator`) is accepted in YAML but not yet applied
> during enforcement -- only exact role matches are checked; and conditional or
> ownership rules require a v0.2 spec, because v0.1 specs do not parse `when` rules.

## Syntax

Declare an `enum` field with the allowed role names, then name that field in
`auth.roles`:

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
      displayName: { type: string, required: true }
      role:
        type: enum
        values: [admin, moderator, user]
        default: user
```

Roles ARE a field. The role lives in a normal enum field on the entity; `auth.roles`
is the pointer that tells the authorizer which field holds the role. There is no
separate entity-level `roles:` block (see [Hierarchy and current limits](#hierarchy-and-current-limits)).

## Behavior

- **Parse time:** `auth.roles` must name a field that exists on the entity
  (`AUTH_ROLES_FIELD_NOT_FOUND`) and that field must be `type: enum`
  (`AUTH_ROLES_FIELD_NOT_ENUM`). The enum's `values`/`default` follow the normal
  rules for an enum field.
- **Compile time:** The role enum is an ordinary field in the generated model. It is
  not given any special storage; it is just another column on the record.
- **Runtime:** On each request the principal's role is read from the configured
  `auth.roles` field on the identity record (falling back to a field named `roles`
  then `role` if `auth.roles` is omitted). Role-scoped access rules match against
  this value by exact comparison.

## Storage

The role is stored as a plain field on the document, alongside the other fields. It
is NOT placed in a special namespace:

```json
{
  "id": "abc-123",
  "email": "admin@example.com",
  "displayName": "Admin",
  "role": "admin"
}
```

Because the role is a regular field, it is returned in CRUD responses like any other
field. If clients should not be able to set or change their own role, restrict the
`create`/`update`/`replace` operations on the controller (see
[Access control](../controllers/access-control.md)); there is no automatic stripping
of the role field on write.

## Options

The role mechanism is two pieces: the `auth.roles` pointer and the enum field it
names.

| Field | Required | Type | Default | Description |
|-------|----------|------|---------|-------------|
| `auth.roles` | no | string | none | Name of the enum field that holds the role. Omit it and the authorizer falls back to a field named `roles` or `role`. |
| field `values` | yes (on the enum field) | list of strings | -- | All valid role names. |
| field `default` | no | string | none | Role assigned by the model default when none is supplied. See the note below on default-on-create. |

## Using roles in access rules

Reference a role from a controller's `access` block. The forms are:

- `entity:role` -- principals of `entity` whose role equals `role`
  (for example `user:admin`).
- bare `role` -- shorthand for `entity:role` when there is exactly one auth entity.
  With two or more auth entities this is ambiguous and raises
  `ACCESS_AMBIGUOUS_ROLE` (use the scoped `entity:role` form). With no auth entity
  it raises `ACCESS_NO_AUTH_ENTITY`.
- `entity:*` -- any authenticated principal of `entity`, regardless of role.

```yaml
controllers:
  myCollection:
    service: myCollection
    access:
      list: public
      create: user:admin       # only users whose role is exactly "admin"
      delete: user:*           # any authenticated user
```

A role name in `entity:role` is matched by exact string comparison. There is no
implicit "admin is also a moderator" inheritance today (see below).

## Examples

### Flat roles

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
      roles: tier
    fields:
      email: { type: string, required: true, unique: true }
      tier:
        type: enum
        values: [free, pro, enterprise]
        default: free
```

`access: user:enterprise` matches only principals whose `tier` is exactly
`enterprise`; it does not match `pro` or `free`.

### Multiple auth entities with separate role fields

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

  apiClient:
    type: auth
    auth:
      identifier: clientId
      via: apiKey
      roles: tier
    fields:
      clientId: { type: string, required: true, unique: true }
      apiKey: { type: string, required: true }
      tier:
        type: enum
        values: [free, premium, enterprise]
        default: free
```

Role names are scoped to their entity. `user:admin` and `apiClient:enterprise` are
independent. With more than one auth entity, always use the scoped `entity:role`
form -- a bare role name raises `ACCESS_AMBIGUOUS_ROLE`.

## Hierarchy and current limits

Role hierarchy (declaring that one role transitively includes another) is configured
in a top-level `roles:` map keyed by auth-entity name, not on the entity:

```yaml
roles:
  user:
    values: [admin, moderator, user]
    default: user
    hierarchy:
      admin: [moderator]
      moderator: [user]
```

This block is parsed and validated (an unknown entity name raises
`ROLES_UNKNOWN_ENTITY`), but the hierarchy is NOT yet applied during enforcement in
any target. Only exact role matches are checked: `access: user:moderator` matches
principals whose role is exactly `moderator`, not `admin`. Treat hierarchy as a
forward-looking declaration; for "admin OR something else" today, list multiple
rules or use a `when` ownership rule. See
[Role hierarchy](./hierarchy.md) for the full detail.

The enum `default` populates the model default, but the create pipeline persists
only fields the client sends (`exclude_unset`). If a client omits the role field on
registration, the default is not written to the stored document, and the principal
resolves with no role until the field is set. To guarantee a role, supply it
server-side (for example via a custom handler) or require it on create.

## Edge Cases

- **Role field must exist and be an enum.** If `auth.roles` names a field that is not
  declared, the parser raises `AUTH_ROLES_FIELD_NOT_FOUND`. If the named field is not
  `type: enum`, it raises `AUTH_ROLES_FIELD_NOT_ENUM`.

- **Role read fallback.** When `auth.roles` is omitted, the authorizer reads a field
  named `roles` (list) or `role` (string) if present. Naming the field explicitly via
  `auth.roles` is clearer.

- **Single role per user.** Each user holds one role string. Access matching compares
  it exactly; there is no transitive expansion (hierarchy is inert, see above).

- **Role is a normal field.** The role value is returned in CRUD responses and is
  writable through `create`/`update`/`replace` unless those operations are restricted
  on the controller. There is no built-in "promote user" endpoint; change a role via a
  guarded update operation or a custom service handler.

- **Entity without a role field.** If an auth entity declares no role field (and none
  is named by `auth.roles`), its principals have no role. Role-scoped rules such as
  `access: user:admin` never match those principals, though `"*"` and
  `user:*` still do.

## Errors

| Condition | Error code | Message |
|-----------|-----------|---------|
| `auth.roles` names a missing field | `AUTH_ROLES_FIELD_NOT_FOUND` | Roles field '<name>' not found in entity '<entity>' |
| `auth.roles` names a non-enum field | `AUTH_ROLES_FIELD_NOT_ENUM` | Roles field '<name>' must be of type 'enum' |
| Top-level `roles:` references an unknown auth entity | `ROLES_UNKNOWN_ENTITY` | Role hierarchy references unknown auth entity '<entity>' |

## See Also

- [Role hierarchy](./hierarchy.md)
- [Auth overview](../auth/overview.md)
- [Access control](../controllers/access-control.md)
