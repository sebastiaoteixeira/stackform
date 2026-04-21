---
title: "Reference: Primary Keys"
description: Controls how entities are uniquely identified -- either via an auto-generated UUID or a client-provided natural key.
---

# Reference: Primary Keys

Controls how entities are uniquely identified -- either via an auto-generated UUID or a client-provided natural key.

## Syntax

### Auto-generated UUID (default)

```yaml
fields:
  id: { type: id }                   # uuidv7 (default)
  id: { type: id, format: uuidv7 }   # explicit uuidv7
  id: { type: id, format: uuidv4 }   # explicit uuidv4
```

### Natural key

```yaml
entities:
  country:
    pk: code
    fields:
      code: { type: string }
      name: { type: string, required: true }
```

## Behavior

### `type: id`

- **Parse time:** If no `type: id` field is declared and no `pk:` is set, an implicit `id: { type: id }` field with `format: uuidv7` is added automatically.
- **Compile time:** The `id` field is excluded from all Pydantic request models (create, update, replace). It is never accepted in request bodies.
- **Runtime:** The server generates the UUID on create. The value is returned in all responses and used as the document identifier in URL path parameters (e.g., `/{id}`).

### `pk: fieldName`

- **Parse time:** The parser verifies the named field exists in `fields:`. No auto-generated `id` field is added. The `idFormat` is set to `"natural"`.
- **Compile time:** The pk field is included in Pydantic create models. The client must provide the value.
- **Runtime:** The pk field value is used as the document identifier in URL path parameters (e.g., `/{code}`). A unique index is enforced.

## Options

### UUID formats

| Format | Description |
|--------|-------------|
| `uuidv7` | Time-ordered UUID. Monotonically increasing; good for index performance. Default. |
| `uuidv4` | Random UUID. No ordering guarantee. |

### Natural key

| Property | Required | Type | Description |
|----------|----------|------|-------------|
| `pk` | no | string (field name) | The field to use as the primary key. Must exist in `fields:`. |

## Examples

### Surrogate key (default)

```yaml
entities:
  post:
    fields:
      id: { type: id }
      title: { type: string, required: true }
```

Creating a post:

```bash
curl -X POST /posts -d '{"title": "Hello"}'
# Returns: {"id": "019...", "title": "Hello"}
```

### Natural key

```yaml
entities:
  country:
    pk: code
    fields:
      code: { type: string }
      name: { type: string, required: true }
```

Creating a country:

```bash
curl -X POST /countries -d '{"code": "US", "name": "United States"}'
# GET /countries/US
```

### Implicit id

```yaml
entities:
  tag:
    fields:
      name: { type: string, required: true }
```

No `type: id` field and no `pk:` declared. An implicit `id: { type: id }` with `format: uuidv7` is added automatically.

## Comparison

| | `type: id` | `pk: fieldName` |
|---|---|---|
| Value source | Server-generated | Client-provided |
| Format | UUID (v7 or v4) | Any field type |
| Path param name | `/{id}` | `/{fieldName}` (e.g., `/{code}`) |
| Auto-index | implicit | unique index enforced |
| Use case | Surrogate keys | Natural / business keys |

## Edge Cases

- **`pk: fieldName` -- field must exist.** The field referenced by `pk:` must be declared in `fields:`. If not, the parser raises `PK_FIELD_NOT_FOUND`.

- **`pk:` with `type: id` field present.** When `pk:` is set, the `pk` field is the primary key. If a `type: id` field also exists, the `id` field is ignored for primary key purposes -- the `pk` field takes precedence. However, both having `pk:` and a `type: id` field simultaneously is an unusual configuration; in practice `pk:` replaces the need for `type: id`.

- **Natural keys are NOT auto-generated.** The client must provide the pk field value on every create request. Omitting it results in a validation error.

- **Natural keys can be any type.** The `pk` field is not restricted to `type: id` or `type: string`. It can be `number`, `string`, or any other type.

- **Duplicate natural key.** If the client sends a `pk` value that already exists, MongoDB raises a duplicate key error (HTTP 409 or 500 depending on error handling).

- **Two `type: id` fields.** If an entity declares two or more fields with `type: id`, the parser raises `ID_FIELD_MULTIPLE`.

## Errors

| Condition | Error code | Message |
|-----------|-----------|---------|
| `pk:` references non-existent field | `PK_FIELD_NOT_FOUND` | "pk field 'X' not found in entity 'Y'" |
| No `type: id` field and no `pk:` | (auto-resolved) | Implicit `id: { type: id }` is added |
| Two or more `type: id` fields | `ID_FIELD_MULTIPLE` | "Entity must define exactly one field with type 'id'" |
| Invalid `format` on `type: id` | `ID_FORMAT_INVALID` | "id field format must be uuidv7 or uuidv4" |

## See Also

- [Field types](./field-types.md)
- [Entities overview](./overview.md)
