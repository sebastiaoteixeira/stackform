---
title: "Entities Overview"
description: Entities define data shapes -- the fields, types, and relationships that make up the application's domain model. Entities have no HTTP or storage behavior; that belongs to repositories and controllers.
---

Entities define data shapes -- the fields, types, and relationships that make up the application's domain model. Entities have no HTTP or storage behavior; that belongs to [repositories](../repositories/overview.md) and [controllers](../controllers/overview.md).

A repository binds an entity to a collection and selects which CRUD operations exist; a controller exposes those operations over HTTP. The collection (and resource path) is named after the repository, not the entity -- see [Behavior](#behavior) below.

## Syntax

```yaml
entities:
  entityName:
    abstract: false          # optional, default: false
    extends: parentName      # optional
    type: auth               # optional, default: base ("auth" marks an identity provider)
    pk: fieldName            # optional, natural primary key
    auth:                    # required with type: auth
      identifier: fieldName
      via:                   # password, apiKey, or binding objects for OIDC/SAML providers
        - password
        - provider: providerName
          identifier: fieldName
      roles: enumFieldName   # optional, names an enum field that holds the role
    roles:                   # optional, only with type: auth
      values: [roleA, roleB]
      default: roleB
      hierarchy:
        roleA: [roleB]
    fields:
      fieldName:
        type: string         # see Field types
        # ... field options
```

## Options

| Property | Required | Type | Default | Description |
|----------|----------|------|---------|-------------|
| `abstract` | no | boolean | `false` | If `true`, the entity is a template only. |
| `extends` | no | string (entity name) | none | Inherits fields, `type`, and `auth` from the named parent entity. |
| `type` | no | `"base"` or `"auth"` | `"base"` | `"auth"` marks the entity as an identity provider. |
| `pk` | no | string (field name) | none | Designates a field as the natural primary key. |
| `auth` | yes with `type: auth` | object | none | Authentication configuration block. |
| `roles` | no; only with `type: auth` | object | none | Declared roles, their default and hierarchy. |
| `fields` | required unless inheriting via `extends:` | map | none | Field definitions. |

### `abstract`

When `true`, the entity is a template only. It does not produce a collection and cannot be bound to a repository. Abstract entities are removed during desugaring; only a repository's `entity:` binding is checked against them, raising `DESUGAR_ABSTRACT_REFERENCED` if a repository points at one. A `ref:` field may name an abstract entity; an unknown name raises `REF_TARGET_NOT_FOUND`.

### `extends`

Inherits from the named entity: all `fields`, and also the parent's `type` and `auth` block when the child does not define its own. The parent must exist in the same `entities:` section. Multi-level chains are supported and resolved parent-first; child fields override inherited fields of the same name. Circular chains raise `ENTITY_CIRCULAR_EXTENDS`. See [inheritance](./inheritance.md).

### `type`

`"base"` (the default) is an ordinary entity. `"auth"` marks the entity as an identity provider, enabling authentication behavior (login, registration, token issuance) configured by its `auth:` block. See [auth overview](../auth/overview.md).

### `pk`

Designates an existing field as the natural primary key. When `pk:` is set, no separate `type: id` field is processed, so do not declare both -- the named field becomes the key directly. The referenced field must exist (`PK_FIELD_NOT_FOUND` otherwise). The client must supply the key on create. See [primary keys](./primary-keys.md).

### `auth`

Authentication configuration for `type: auth` entities. Holds `identifier`, `via` (credential providers and binding objects for external providers), and an optional `roles` (the name of an enum field carrying the role). The `password` and `passwordHash` fields are implicit when `via` includes `password` -- declaring them yourself is rejected. See [auth overview](../auth/overview.md).

### `roles`

An auth entity holds roles in one of two ways. A `roles:` block declares managed roles, kept out of the entity's fields:

```yaml
entities:
  user:
    type: auth
    auth:
      identifier: email
      via: password
    roles:
      values: [admin, editor, viewer]
      default: viewer
      hierarchy:
        admin: [editor]
    fields:
      id: { type: id }
      email: { type: string, required: true, unique: true }
```

Or `auth.roles` names an `enum` field that holds the role:

```yaml
entities:
  user:
    type: auth
    auth:
      identifier: email
      via: password
      roles: role            # names the enum field below
    fields:
      id: { type: id }
      email: { type: string, required: true, unique: true }
      role:
        type: enum
        values: [admin, editor, viewer]
        default: viewer
```

Roles are read at request time, from the enum field or from the managed store. A `roles:` block may accompany the enum field to add a hierarchy. See [roles overview](../roles/overview.md).

### `fields`

Map of field name to field definition. Required unless the entity fully inherits its fields via `extends:`. See [field types](./field-types.md).

## Behavior

- **Parse time:** Entity names are validated for uniqueness. `extends:` references are resolved (fields, `type`, and `auth` inherited) and circular chains are rejected. Abstract entities are stripped during desugaring. An auth entity's `auth.roles` must name an existing `enum` field, and a `roles:` block must keep its default and hierarchy within its `values`.
- **Compile time:** The collection and resource name come from the **repository** name that binds the entity (free-form; no pluralization). An entity referenced by two repositories produces two collections.
- **Runtime:** Each repository-bound entity produces a collection. Roles are read from the configured enum field or the managed store.

## Examples

The URLs each example produces depend on the `api:` block. With `api: { basePath: /api, version: v1 }`, a repository named `myCollection` is served under `/api/v1/my-collection`.

### Minimal entity

```yaml
api:
  basePath: /api
  version: v1

entities:
  myEntity:
    fields:
      id: { type: id }
      title: { type: string, required: true }
      body: { type: string }

repositories:
  myCollection:
    entity: myEntity  # collection + path are named "myCollection" (the repository)
```

### Auth entity with roles

```yaml
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
    roles:
      values: [admin, moderator, user]
      default: user
      hierarchy:
        admin: [moderator]
        moderator: [user]
```

### Inheritance with abstract base

```yaml
entities:
  base:
    abstract: true
    fields:
      id: { type: id }
      createdAt: { type: datetime }

  user:
    extends: base          # inherits id, createdAt
    type: auth
    auth:
      identifier: email
      via: password
    fields:
      email: { type: string, required: true, unique: true }
      displayName: { type: string, required: true }

  country:
    pk: code               # natural key; no separate id field
    fields:
      code: { type: string }
      name: { type: string, required: true }
```

## Edge Cases

- **Entity names are case-sensitive.** `user` and `User` are different entities.
- **Collection naming follows the repository.** The collection and resource path are named after the binding repository, not the entity, and are not pluralized. A `user` entity bound by a `members` repository yields a `members` collection at `.../members`.
- **No fields and no `extends:`.** An entity with no `fields:` and no `extends:` is a schema validation error. The `fields` property is required unless the entity inherits via `extends:`.
- **Exactly one id field, unless `pk:`.** A non-`pk` entity needs exactly one `type: id` field; none raises `ID_FIELD_MISSING`, more than one raises `ID_FIELD_MULTIPLE`. The id defaults to a server-generated uuidv7.
- **`password` / `passwordHash` are implicit.** When `via` includes `password`, these fields are managed for you; declaring either raises `AUTH_PASSWORD_FIELD_FORBIDDEN` / `AUTH_PASSWORD_HASH_FIELD_FORBIDDEN`.
- **`auth.roles` must name an enum field.** A missing target raises `AUTH_ROLES_FIELD_NOT_FOUND`; a non-enum target raises `AUTH_ROLES_FIELD_NOT_ENUM`.

## Errors

| Condition | Error code | Message |
|-----------|-----------|---------|
| `fields` missing and no `extends:` | schema validation error | `fields` is required |
| No `type: id` field and no `pk:` | `ID_FIELD_MISSING` | "Entity must define exactly one field with type 'id'" |
| More than one `type: id` field | `ID_FIELD_MULTIPLE` | "Entity must define exactly one field with type 'id'" |
| `pk:` references a missing field | `PK_FIELD_NOT_FOUND` | "pk field 'X' not found in entity 'Y'" |
| `extends:` references unknown entity | `ENTITY_EXTENDS_NOT_FOUND` | "Entity 'X' extends unknown entity 'Y'" |
| Circular `extends:` chain | `ENTITY_CIRCULAR_EXTENDS` | "Circular inheritance detected involving entity 'X'" |
| Repository binds an abstract entity | `DESUGAR_ABSTRACT_REFERENCED` | "Repository 'X' references abstract entity 'Y'" |
| `auth.roles` names a missing field | `AUTH_ROLES_FIELD_NOT_FOUND` | "Roles field 'X' not found in entity 'Y'" |
| `auth.roles` field is not an enum | `AUTH_ROLES_FIELD_NOT_ENUM` | "Roles field 'X' must be of type 'enum'" |
| `roles.default` is not in `roles.values` | `ROLES_DEFAULT_UNKNOWN_ROLE` | "Default role 'X' is not one of the declared roles" |
| `roles.hierarchy` names an undeclared role | `ROLES_HIERARCHY_UNKNOWN_ROLE` | "Role hierarchy references undeclared role 'X'" |
| `roles.hierarchy` is cyclic | `ROLES_HIERARCHY_CYCLE` | "Role hierarchy for 'Y' is cyclic through 'X'" |
| `ref:` names an undeclared entity | `REF_TARGET_NOT_FOUND` | "Field references undeclared record type 'X'" |
| `type: auth` without `auth`, or `roles` without `type: auth` | `SCHEMA_VALIDATION_ERROR` | |
| Declaring `password` on an auth entity | `AUTH_PASSWORD_FIELD_FORBIDDEN` | "Password input is implicit when auth.via includes password" |
| Declaring `passwordHash` on an auth entity | `AUTH_PASSWORD_HASH_FIELD_FORBIDDEN` | "passwordHash is implicit storage when auth.via includes password" |

## See Also

- [Field types](./field-types.md)
- [Entity inheritance](./inheritance.md)
- [Primary keys](./primary-keys.md)
- [Auth overview](../auth/overview.md)
- [Roles overview](../roles/overview.md)
