# Reference: Entities Overview

Entities define data shapes -- the fields, types, and relationships that make up the application's domain model. Entities have no HTTP or storage behavior; that belongs to [repositories](../repositories/overview.md) and [controllers](../controllers/overview.md).

## Syntax

```yaml
entities:
  entityName:
    abstract: false          # optional, default: false
    extends: parentName      # optional
    type: auth               # optional, only valid value is "auth"
    pk: fieldName            # optional, natural primary key
    auth:                    # required if type: auth
      identifier: fieldName
      via: password           # or apiKey, or [password, apiKey]
    roles:                   # optional, entity-level role config
      values: [...]
      default: roleName
      hierarchy:
        roleName: [includedRole, ...]
    fields:
      fieldName:
        type: <fieldType>
        # ... field options
```

## Options

| Property | Required | Type | Default | Description |
|----------|----------|------|---------|-------------|
| `abstract` | no | boolean | `false` | If `true`, the entity is a template only. |
| `extends` | no | string (entity name) | none | Inherits all fields from the named parent entity. |
| `type` | no | `"auth"` | none | Marks the entity as an identity provider. |
| `pk` | no | string (field name) | none | Designates a field as the natural primary key. |
| `auth` | required if `type: auth` | object | none | Authentication configuration block. |
| `roles` | no | object | none | Role definitions for this auth entity. |
| `fields` | required unless inheriting via `extends:` | map | none | Field definitions. |

### `abstract`

When `true`, the entity is a template only. It does not produce a MongoDB collection and cannot be referenced in `ref:` fields or bound to a repository. Abstract entities are removed from the IR after desugaring.

### `extends`

Inherits all fields from the named entity. The parent must exist in the same `entities:` section. Only single inheritance is supported. See [inheritance](./inheritance.md).

### `type`

Only valid value: `"auth"`. Marks the entity as an identity provider, enabling authentication behavior (login, registration, token issuance). Requires the `auth:` block. See [auth overview](../auth/overview.md).

### `pk`

Designates a field as the natural primary key. When `pk:` is set, no auto-generated `id` field is added. The referenced field can be any type. See [primary keys](./primary-keys.md).

### `auth`

Authentication configuration. Required when `type: auth`. Contains `identifier` and `via`. See [auth overview](../auth/overview.md).

### `roles`

Entity-level role configuration. Only valid on `type: auth` entities. Contains `values`, `default`, and optionally `hierarchy`. See [roles overview](../roles/overview.md).

### `fields`

Map of field name to field definition. Required unless the entity fully inherits its fields via `extends:`. See [field types](./field-types.md).

## Behavior

- **Parse time:** Entity names are validated for uniqueness. `extends:` references are resolved. Abstract entities are stripped after desugaring. `type: auth` requires an `auth:` block.
- **Compile time:** Entity names map to MongoDB collection names by appending `s` (e.g., `user` produces `users`). This naming is not configurable in v0.2.
- **Runtime:** Each non-abstract entity with a bound repository produces a MongoDB collection.

## Examples

### Minimal entity

```yaml
entities:
  note:
    fields:
      id: { type: id }
      title: { type: string, required: true }
      body: { type: string }
```

### Auth entity with roles

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

### Inheritance with abstract base

```yaml
entities:
  base:
    abstract: true
    fields:
      id: { type: id }
      createdAt: { type: datetime }

  user:
    extends: base
    type: auth
    auth:
      identifier: email
      via: password
    fields:
      email: { type: string, required: true, unique: true }
      displayName: { type: string, required: true }

  country:
    pk: code
    fields:
      code: { type: string }
      name: { type: string, required: true }
```

## Edge Cases

- **Entity names are case-sensitive.** `user` and `User` are different entities.
- **Entity-to-collection naming.** Entity names map to collection names by appending `s` (e.g., `user` produces `users`). This is not configurable in v0.2.
- **No fields and no `extends:`.** An entity with no `fields:` and no `extends:` is a schema validation error. The `fields` property is required unless the entity inherits via `extends:`.
- **`type: auth` without `auth:` block.** Parse error. The `auth:` block is required when `type: auth` is set.
- **`type: auth` with empty `via:`.** Parse error. At least one authentication method must be specified.

## Errors

| Condition | Error code | Message |
|-----------|-----------|---------|
| `fields` missing and no `extends:` | schema validation error | `fields` is required |
| `type: auth` without `auth:` block | schema validation error | `auth` is required when type is "auth" |
| `extends:` references unknown entity | `ENTITY_EXTENDS_NOT_FOUND` | "Entity 'X' extends unknown entity 'Y'" |
| Repository references abstract entity | `DESUGAR_ABSTRACT_REFERENCED` | "Repository 'X' references abstract entity 'Y'" |

## See Also

- [Field types](./field-types.md)
- [Entity inheritance](./inheritance.md)
- [Primary keys](./primary-keys.md)
- [Auth overview](../auth/overview.md)
- [Roles overview](../roles/overview.md)
