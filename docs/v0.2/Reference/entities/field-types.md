---
title: "Field Types"
description: Declares the type and constraints for each field in an entity's `fields:` map.
---

Declares the type and constraints for each field in an entity's `fields:` map.

## Syntax

All fields are declared under `fields:` in an entity definition. Each field must specify a `type`.

```yaml
fields:
  fieldName:
    type: <id | string | number | boolean | datetime | enum | array | object | ref>
    required: <boolean>
    unique: <boolean>
    default: <value>
```

## Common Options

These options apply to all field types.

| Option | Required | Type | Default | Description |
|--------|----------|------|---------|-------------|
| `required` | no | boolean | `false` | If `true`, the field must be present in create payloads. |
| `unique` | no | boolean | `false` | If `true`, a MongoDB unique index is created on this field. |
| `default` | no | any | none | Server-side default applied when the field is omitted on create. |

## `type: id`

Auto-generated UUID primary key.

```yaml
id: { type: id }                   # uuidv7 (default)
id: { type: id, format: uuidv7 }   # explicit uuidv7
id: { type: id, format: uuidv4 }   # explicit uuidv4
```

| Option | Required | Type | Default | Description |
|--------|----------|------|---------|-------------|
| `format` | no | `"uuidv7"` or `"uuidv4"` | `"uuidv7"` | UUID generation strategy. |

### Behavior

- **Parse time:** If the entity has no `type: id` field and no `pk:` declaration, an implicit `id: { type: id }` field is added with `format: uuidv7`.
- **Compile time:** The `id` field is excluded from all Pydantic request models (create, update, replace).
- **Runtime:** The server generates the UUID value on create. The value is returned in all responses.

## `type: string`

UTF-8 text value.

```yaml
name: { type: string }
email: { type: string, required: true, unique: true }
bio: { type: string, default: "" }
email: { type: string, format: email }
```

| Option | Required | Type | Default | Description |
|--------|----------|------|---------|-------------|
| `format` | no | `"email"`, `"e164"`, `"uri"` | none | Hint for OpenAPI schema generation. |
| `minLength` | no | integer | none | Minimum character count. |
| `maxLength` | no | integer | none | Maximum character count. |

## `type: number`

Integer or floating-point number.

```yaml
age: { type: number }
price: { type: number, required: true }
viewCount: { type: number, default: 0 }
```

| Option | Required | Type | Default | Description |
|--------|----------|------|---------|-------------|
| `min` | no | number | none | Minimum value (inclusive). |
| `max` | no | number | none | Maximum value (inclusive). |

## `type: boolean`

True or false.

```yaml
active: { type: boolean, default: true }
published: { type: boolean, default: false }
```

No type-specific options.

## `type: datetime`

ISO 8601 timestamp. Stored as a MongoDB Date.

```yaml
createdAt: { type: datetime }
expiresAt: { type: datetime, required: true }
```

Clients send and receive RFC 3339 strings (e.g., `"2024-01-15T10:00:00Z"`).

No type-specific options.

## `type: enum`

One of a fixed set of string values.

```yaml
status:
  type: enum
  values: [draft, published, archived]
  default: draft
```

| Option | Required | Type | Default | Description |
|--------|----------|------|---------|-------------|
| `values` | yes | list of strings | -- | The allowed values. Must be non-empty. |
| `default` | no | string | none | Must be one of the declared `values`. |

## `type: array`

A list of items.

```yaml
tags:
  type: array
  items:
    type: string

scores:
  type: array
  items:
    type: number
```

| Option | Required | Type | Default | Description |
|--------|----------|------|---------|-------------|
| `items` | yes | field config | -- | Schema for array elements. Supports any `type`. |

## `type: object`

A free-form JSON object. No nested schema validation is performed on its contents.

```yaml
metadata: { type: object }
settings: { type: object }
```

No type-specific options.

## `type: ref`

A reference to another entity. Stores the referenced entity's primary key value.

```yaml
authorId: { type: ref, ref: user }
listId: { type: ref, ref: list, required: true }
```

| Option | Required | Type | Default | Description |
|--------|----------|------|---------|-------------|
| `ref` | yes | string (entity name) | -- | The entity name (singular). Must match a key in `entities:`. |

### Behavior

- **Parse time:** The `ref` value is validated against entity names.
- **Runtime:** The stored value is the raw primary key string. No automatic join is performed.

## Examples

### Happy path: entity with all field types

```yaml
entities:
  note:
    fields:
      id: { type: id }
      title: { type: string, required: true }
      body: { type: string }
      viewCount: { type: number, default: 0 }
      pinned: { type: boolean, default: false }
      status:
        type: enum
        values: [draft, published, archived]
        default: draft
      publishedAt: { type: datetime }
      tags:
        type: array
        items:
          type: string
      metadata: { type: object }
      authorId: { type: ref, ref: user }
```

### Edge case: `required: true` with `default:`

```yaml
status:
  type: enum
  values: [draft, published]
  default: draft
  required: true
```

The `default` satisfies the requirement. If the field is omitted from the request, the server fills it with `draft`. If the client sends a value explicitly, the sent value is used.

## Edge Cases

- **`required: true` with `default:`** -- The default value satisfies the requirement. Omitting the field from the request body does not cause a validation error; the server fills the default. If the client sends a value, the sent value takes precedence.

- **`unique: true`** -- Enforced via a MongoDB unique index. Multiple `null` values are NOT allowed (MongoDB treats `null` as a value for uniqueness). If the field is optional and omitted, it is stored as absent (not `null`), which avoids the unique-null problem.

- **`type: id` -- only one per entity.** An entity must have at most one field with `type: id`. If zero `id` fields exist and no `pk:` is set, an implicit `id: { type: id }` is added. If two or more `id` fields are declared, parse fails with `ID_FIELD_MULTIPLE`.

- **`type: id` -- never in payloads.** The `id` field is never accepted in create or update request bodies. It is always server-generated and returned in responses.

- **`type: ref` -- no referential integrity.** The `ref` field stores the referenced entity's primary key value. MongoDB has no foreign key constraints, so referential integrity is NOT enforced. Dangling references are possible if the referenced document is deleted.

- **`type: ref` -- non-existent target.** If `ref:` points to an entity name that does not exist in `entities:`, the parser raises an error.

- **`type: ref` -- abstract target.** If `ref:` points to an entity with `abstract: true`, the parser raises an error. Abstract entities are removed after desugaring and cannot be referenced.

- **`type: enum` -- invalid payload value.** If a create or update payload sends a value not in `values`, Pydantic validation rejects it with HTTP 422.

- **`type: enum` -- invalid default.** If `default:` is not one of the declared `values`, the parser raises an error.

- **`type: array` -- untyped items.** The `items` sub-schema supports any field type. There are no nested type constraints beyond what `items.type` declares.

- **`type: object` -- no nested validation.** Stored as-is. Any valid JSON object is accepted. No nested schema validation is performed.

- **`format: email` on string** -- NOT validated by the server at runtime. It is a hint for documentation and OpenAPI schema generation only.

## Errors

| Condition | Error code | Message |
|-----------|-----------|---------|
| Two or more `type: id` fields on one entity | `ID_FIELD_MULTIPLE` | "Entity must define exactly one field with type 'id'" |
| `type: id` with invalid `format` | `ID_FORMAT_INVALID` | "id field format must be uuidv7 or uuidv4" |
| `type: ref` with unknown entity | parse error | ref target not found in `entities:` |
| `type: ref` with abstract entity | parse error | abstract entities cannot be ref targets |
| `type: enum` with no `values` | schema validation | `values` is required for enum fields |
| `type: enum` with `default` not in `values` | parse error | default must be one of the declared values |
| `type: array` with no `items` | schema validation | `items` is required for array fields |

## See Also

- [Entities overview](./overview.md)
- [Primary keys](./primary-keys.md)
- [Entity inheritance](./inheritance.md)
