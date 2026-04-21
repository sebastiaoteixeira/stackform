# Reference: Entities Overview

Entities define data shapes. They are the source of truth for fields, types, and relationships. Entities have no HTTP or storage behavior — that belongs to repositories and controllers.

## Top-level structure

```yaml
entities:
  entityName:
    abstract: false          # optional, default: false
    extends: parentName      # optional
    type: auth               # optional, only value is "auth"
    via: [...]               # required if type: auth
    roles: fieldName         # optional, used with type: auth
    pk: fieldName            # optional, overrides auto-generated id
    fields:
      fieldName:
        type: <fieldType>
        # ... field options
```

## Properties

### `abstract`

Type: boolean. Default: `false`.

When `true`, the entity is a template only. It does not produce a MongoDB collection and cannot be referenced in `ref:` fields or bound to a repository. Removed from the IR after desugaring.

### `extends`

Type: string (entity name). Optional.

Inherits all fields from the named entity. The parent must exist in the same `entities:` section. Only one parent is allowed. See [inheritance](./inheritance.md).

### `type`

Type: string. Optional. Only valid value: `"auth"`.

Marks the entity as an identity provider. Enables authentication behavior (login, registration, token issuance). Requires `via:` to specify at least one provider binding.

### `via`

Type: list of provider bindings. Required when `type: auth`.

Defines how principals authenticate. Each binding has `provider:`, `identifier:`, and optional `claim_mapping:` and `auto_provision:`. See [auth overview](../auth/overview.md).

### `roles`

Type: string (field name). Optional. Used with `type: auth`.

Points to an enum field on this entity that holds the principal's role. Enables role-based access control for this entity.

### `pk`

Type: string (field name). Optional.

Designates a field as the natural primary key. When `pk:` is set, no auto-generated `id` field is added. The referenced field can be any type. See [primary-keys](./primary-keys.md).

### `fields`

Type: map of field name to field definition. Required (unless fully inherited via `extends:`).

See [field-types](./field-types.md) for all available types and options.

## Example

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
    via:
      - provider: password
        identifier: email
    roles: role
    fields:
      email: { type: string, required: true, unique: true }
      displayName: { type: string, required: true }
      role:
        type: enum
        values: [admin, moderator, user]
        default: user

  country:
    pk: code
    fields:
      code: { type: string }
      name: { type: string, required: true }
```
