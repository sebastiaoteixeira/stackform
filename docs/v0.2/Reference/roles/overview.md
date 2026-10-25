---
title: "Roles Overview"
description: Declare per-user roles on an auth entity, either as managed roles or as an enum field named by auth.roles, and use them in access rules.
---

A role belongs to a record of a `type: auth` entity. It is read on every request and
matched by role-scoped access rules such as `access: user:admin`. An entity keeps its
roles in one of two ways:

- **Managed roles:** an entity-level `roles:` block. The roles live in the record's
  internal `_auth` namespace, are not part of the API's fields, and are never written
  through the API.
- **A role field:** `auth.roles` names an `enum` field. The role is an ordinary field,
  returned in responses and set through the API within the limits below.

> **Enforcement**
>
> Roles, role hierarchies, `<entity>:*` scoping, and ownership/ABAC `when` rules
> are enforced by the generated FastAPI backend, the generated DRF backend, and the
> `stackform run` dev server alike. A request that no rule admits gets 401 when it
> carries no valid credentials and 403 otherwise; a missing record answers 404
> before ownership is checked.

## Syntax

### Managed roles

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
    fields:
      id: { type: id }
      email: { type: string, required: true, unique: true }
      displayName: { type: string, required: true }

repositories:
  users:
    entity: user
```

### A role field

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
      id: { type: id }
      email: { type: string, required: true, unique: true }
      displayName: { type: string, required: true }
      role:
        type: enum
        values: [admin, moderator, user]
        default: user

repositories:
  users:
    entity: user
```

An entity may declare both: the roles then live in the `auth.roles` field, and the
`roles:` block adds a hierarchy and the default role.

## Behavior

- **Parse time:** `roles.default` must be one of `roles.values`
  (`ROLES_DEFAULT_UNKNOWN_ROLE`), and `roles.hierarchy` must name declared roles
  without a cycle (see [Role hierarchy](./hierarchy.md)). `auth.roles` must name a
  field of the entity (`AUTH_ROLES_FIELD_NOT_FOUND`) of `type: enum`
  (`AUTH_ROLES_FIELD_NOT_ENUM`). A role named in an access rule must be one the entity
  declares in `roles.values` or its role field (`ACCESS_RULE_INVALID`).
- **Runtime:** on each request the principal's roles are read from the `auth.roles`
  field, or from `_auth.roles` when the entity names no role field. A principal
  holds its roles plus every role its hierarchy includes.

## Storage

Managed roles are stored under `_auth.roles` on the identity record:

```json
{
  "id": "abc-123",
  "email": "admin@example.com",
  "displayName": "Admin",
  "_auth": { "passwordHash": "pbkdf2$sha256$...", "roles": "admin" }
}
```

Every new record gets `roles.default`. To change a managed role, update the stored
record directly; the API offers no way to write it. With SQLite:

```sql
UPDATE users SET _auth = json_set(_auth, '$.roles', 'admin') WHERE email = 'admin@example.com';
```

With MongoDB:

```js
db.users.updateOne({ email: "admin@example.com" }, { $set: { "_auth.roles": "admin" } })
```

A role field is stored as a plain field and returned in CRUD responses. A caller
sets it only to roles it holds itself, counting the roles its hierarchy includes:

- On create, a record whose role field names a role the caller does not hold, or
  that omits the field, gets the default role.
- On update or replace, a role change the caller does not hold is dropped and the
  rest of the change applies.

So a public `register` always yields the default role, and only an `admin` can make
another user an `admin`.

## Options

| Field | Required | Type | Description |
|-------|----------|------|-------------|
| `roles.values` | yes | list of strings | All valid role names. |
| `roles.default` | yes | string | Role of a new record. |
| `roles.hierarchy` | no | map of role to list of roles | Roles each role includes. See [Role hierarchy](./hierarchy.md). |
| `auth.roles` | no | string | Name of an `enum` field that holds the role. Its `values` are the roles and its `default` the role of a new record. |

## Using roles in access rules

Reference a role from an access value. The forms are:

- `entity:role` -- principals of `entity` holding `role` (for example `user:admin`).
- bare `role` -- shorthand for `entity:role` when there is exactly one auth entity.
  With two or more auth entities this is ambiguous and raises
  `ACCESS_AMBIGUOUS_ROLE` (use the scoped `entity:role` form). With no auth entity
  it raises `ACCESS_NO_AUTH_ENTITY`.
- `entity:*` -- any authenticated principal of `entity`, regardless of role.

```yaml
controllers:
  myCollection:
    service: myCollection
    operations:
      list: { access: public }
      create: { access: user:admin }   # users holding "admin"
      delete: { access: user:* }       # any authenticated user
```

## Examples

### Multiple auth entities

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
    fields:
      id: { type: id }
      email: { type: string, required: true, unique: true }

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
      tier:
        type: enum
        values: [free, premium, enterprise]
        default: free

repositories:
  users:
    entity: user
  apiClients:
    entity: apiClient
```

Role names are scoped to their entity. `user:admin` and `apiClient:enterprise` are
independent. With more than one auth entity, always use the scoped `entity:role`
form -- a bare role name raises `ACCESS_AMBIGUOUS_ROLE`.

## Edge Cases

- **One role per record.** A role field or managed store holds one role name; the
  hierarchy decides which other roles it implies.

- **Entity without roles.** With neither a `roles:` block nor `auth.roles`, the
  entity's principals hold no role. Role-scoped rules such as `access: user:admin`
  never match them, though `"*"` and `user:*` still do.

## Errors

| Condition | Error code | Message |
|-----------|-----------|---------|
| `roles.default` is not in `roles.values` | `ROLES_DEFAULT_UNKNOWN_ROLE` | Default role '<role>' is not one of the declared roles |
| `roles.hierarchy` names an undeclared role | `ROLES_HIERARCHY_UNKNOWN_ROLE` | Role hierarchy references undeclared role '<role>' |
| `roles.hierarchy` is cyclic | `ROLES_HIERARCHY_CYCLE` | Role hierarchy for '<entity>' is cyclic through '<role>' |
| `auth.roles` names a missing field | `AUTH_ROLES_FIELD_NOT_FOUND` | Roles field '<name>' not found in entity '<entity>' |
| `auth.roles` names a non-enum field | `AUTH_ROLES_FIELD_NOT_ENUM` | Roles field '<name>' must be of type 'enum' |
| An access rule names a role the entity does not declare | `ACCESS_RULE_INVALID` | role '<role>' is not declared in entity '<entity>' |

## See Also

- [Role hierarchy](./hierarchy.md)
- [Auth overview](../auth/overview.md)
- [Access control](../controllers/access-control.md)
