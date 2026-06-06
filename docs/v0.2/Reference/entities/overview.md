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
    auth:                    # required in practice when type: auth
      identifier: fieldName
      via: password          # or apiKey, or [password, apiKey]
      roles: enumFieldName   # optional, names an enum field that holds the role
      bindings:              # optional, external identity providers (OIDC/SAML)
        - provider: providerName
          identifier: fieldName
    fields:
      fieldName:
        type: <fieldType>
        # ... field options
```

## Options

| Property | Required | Type | Default | Description |
|----------|----------|------|---------|-------------|
| `abstract` | no | boolean | `false` | If `true`, the entity is a template only. |
| `extends` | no | string (entity name) | none | Inherits fields, `type`, and `auth` from the named parent entity. |
| `type` | no | `"base"` or `"auth"` | `"base"` | `"auth"` marks the entity as an identity provider. |
| `pk` | no | string (field name) | none | Designates a field as the natural primary key. |
| `auth` | effectively required if `type: auth` | object | none | Authentication configuration block. |
| `fields` | required unless inheriting via `extends:` | map | none | Field definitions. |

### `abstract`

When `true`, the entity is a template only. It does not produce a collection and cannot be bound to a repository. Abstract entities are removed during desugaring; only a repository's `entity:` binding is checked against them, raising `DESUGAR_ABSTRACT_REFERENCED` if a repository points at one. A plain `ref:` field that names an abstract (or unknown) entity is not validated.

### `extends`

Inherits from the named entity: all `fields`, and also the parent's `type` and `auth` block when the child does not define its own. The parent must exist in the same `entities:` section. Multi-level chains are supported and resolved parent-first; child fields override inherited fields of the same name. Circular chains raise `ENTITY_CIRCULAR_EXTENDS`. See [inheritance](./inheritance.md).

### `type`

`"base"` (the default) is an ordinary entity. `"auth"` marks the entity as an identity provider, enabling authentication behavior (login, registration, token issuance). In practice this requires an `auth:` block. See [auth overview](../auth/overview.md).

### `pk`

Designates an existing field as the natural primary key. When `pk:` is set, no separate `type: id` field is processed, so do not declare both -- the named field becomes the key directly. The referenced field must exist (`PK_FIELD_NOT_FOUND` otherwise). The client must supply the key on create. See [primary keys](./primary-keys.md).

### `auth`

Authentication configuration for `type: auth` entities. Holds `identifier`, `via`, an optional `roles` (the name of an enum field carrying the role), and optional `bindings` for external providers. The `password` and `passwordHash` fields are implicit when `via` includes `password` -- declaring them yourself is rejected. See [auth overview](../auth/overview.md).

### `roles`

There is no entity-level `roles:` block in v0.2. To give an auth entity roles, declare an `enum` field and point `auth.roles` at it:

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

The role value is read from that enum field at request time. The new-user default comes from the enum field's own `default:`, not from any separate role config. Role hierarchy is configured by a separate top-level `roles:` map (a sibling of `entities:`), keyed by auth-entity name; that hierarchy is parsed but not yet applied during enforcement -- only exact role matches are checked. See [roles overview](../roles/overview.md).

### `fields`

Map of field name to field definition. Required unless the entity fully inherits its fields via `extends:`. See [field types](./field-types.md).

## Behavior

- **Parse time:** Entity names are validated for uniqueness. `extends:` references are resolved (fields, `type`, and `auth` inherited) and circular chains are rejected. Abstract entities are stripped during desugaring. An auth entity's `auth.roles` must name an existing `enum` field.
- **Compile time:** The collection and resource name come from the **repository** name that binds the entity (free-form; no pluralization). An entity referenced by two repositories produces two collections.
- **Runtime:** Each repository-bound entity produces a collection. Roles are read from the configured enum field.

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

# Optional hierarchy (UI/declarative only; not applied during enforcement)
roles:
  user:
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
| Declaring `password` on an auth entity | `AUTH_PASSWORD_FIELD_FORBIDDEN` | "Password input is implicit when auth.via includes password" |
| Declaring `passwordHash` on an auth entity | `AUTH_PASSWORD_HASH_FIELD_FORBIDDEN` | "passwordHash is implicit storage when auth.via includes password" |

## See Also

- [Field types](./field-types.md)
- [Entity inheritance](./inheritance.md)
- [Primary keys](./primary-keys.md)
- [Auth overview](../auth/overview.md)
- [Roles overview](../roles/overview.md)
