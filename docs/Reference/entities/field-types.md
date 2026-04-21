# Reference: Field Types

All fields are declared under `fields:` in an entity definition.

## Common options (apply to all types)

| Option | Type | Description |
|--------|------|-------------|
| `required` | boolean | Field must be present on create. Default: `false`. |
| `unique` | boolean | Value must be unique across the collection. Enforced via MongoDB index. Default: `false`. |
| `default` | any | Server-side default applied when the field is omitted on create. |

## `type: id`

Auto-generated UUID. Implicitly the primary key unless `pk:` is set on the entity.

```yaml
id: { type: id }
id: { type: id, format: uuidv7 }   # default
id: { type: id, format: uuidv4 }   # explicit uuidv4
```

Options:
- `format`: `uuidv7` (default, time-ordered) or `uuidv4` (random). No other options.

The `id` field is never accepted in request bodies. It is always generated server-side.

## `type: string`

UTF-8 text value.

```yaml
name: { type: string }
email: { type: string, required: true, unique: true }
bio: { type: string, default: "" }
```

## `type: number`

Integer or floating-point number.

```yaml
age: { type: number }
price: { type: number, required: true }
viewCount: { type: number, default: 0 }
```

## `type: boolean`

True or false.

```yaml
active: { type: boolean, default: true }
published: { type: boolean, default: false }
```

## `type: datetime`

ISO 8601 timestamp. Stored as a MongoDB Date.

```yaml
createdAt: { type: datetime }
publishedAt: { type: datetime }
expiresAt: { type: datetime, required: true }
```

Clients send and receive RFC 3339 strings (e.g., `"2024-01-15T10:00:00Z"`).

## `type: enum`

One of a fixed set of string values.

```yaml
status:
  type: enum
  values: [draft, published, archived]
  default: draft

role:
  type: enum
  values: [admin, moderator, user]
  default: user
```

Required options:
- `values`: list of allowed string values. Non-empty.

Optional options:
- `default`: must be one of the declared values.

## `type: array`

A list of items. The item schema is declared under `items:`.

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

`items:` supports nested field type declarations including `type: object` for arrays of objects.

## `type: object`

A free-form JSON object. No schema enforcement on the object's contents.

```yaml
metadata: { type: object }
settings: { type: object }
```

## `type: ref`

A foreign key reference to another entity. Stores the primary key value of a document in the referenced entity's collection.

```yaml
authorId: { type: ref, ref: user }
listId: { type: ref, ref: list, required: true }
```

Required options:
- `ref`: the entity name (singular). Must match a key in `entities:`.

No automatic join is performed. The stored value is the raw ID string.
