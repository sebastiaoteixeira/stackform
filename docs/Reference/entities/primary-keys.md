# Reference: Primary Keys

## Default: `type: id`

Declare a field with `type: id` to get an auto-generated UUID primary key.

```yaml
fields:
  id: { type: id }             # uuidv7, default
  id: { type: id, format: uuidv7 }  # explicit
  id: { type: id, format: uuidv4 }  # random UUID
```

The field name can be anything, but `id` is conventional. The field is:
- Never accepted in request bodies (always server-generated)
- Returned in all responses
- Used as the document identifier in URL path parameters (`/{id}`)

### UUID formats

| Format | Description |
|--------|-------------|
| `uuidv7` | Time-ordered UUID (default). Monotonically increasing, good for index performance. |
| `uuidv4` | Random UUID. No ordering guarantee. |

### Implicit id

If no `type: id` field is declared on an entity (and no `pk:` is set), an implicit `id` field with `format: uuidv7` is added automatically.

## Natural keys: `pk:`

`pk: fieldName` designates an existing field as the primary key. No auto-generated `id` is added.

```yaml
entities:
  country:
    pk: code
    fields:
      code: { type: string }
      name: { type: string, required: true }

  currency:
    pk: iso
    fields:
      iso: { type: string }
      name: { type: string }
      symbol: { type: string }
```

The `pk` field:
- Can be any field type (string, number, etc.)
- Is used as the document identifier in URL path parameters (`/{code}`, `/{iso}`)
- Must be unique — the engine enforces a unique index on this field
- Is required on create (must be provided by the client)

## Comparison

| | `type: id` | `pk: fieldName` |
|---|---|---|
| Value source | Server-generated | Client-provided |
| Format | UUID | Any type |
| Path param name | `/posts/{id}` | `/countries/{code}` |
| Auto-index | implicit | unique index enforced |
| Use case | Surrogate keys | Natural / business keys |

## Example with both patterns

```yaml
entities:
  # Surrogate key — auto-generated UUID
  post:
    fields:
      id: { type: id }
      title: { type: string, required: true }

  # Natural key — client supplies the code
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
