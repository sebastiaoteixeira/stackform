---
title: "Tutorial 02: Field Types"
description: All available field types with their options.
---

**Concept introduced:** All available field types with their options.

## Adding a richer entity

Extend the note entity from tutorial 01 to demonstrate every field type:

```yaml
version: "0.2"

mongo:
  uri: mongodb://localhost:27017
  database: myapp

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
      metadata:
        type: object

repositories:
  notes:
    entity: note

services:
  notes: {}

controllers:
  notes:
    service: notes
    base_path: /notes
    access: public
```

## Field type reference

| Type | Description | Extra options |
|------|-------------|---------------|
| `id` | Auto-generated UUID, implicitly the primary key | `format: uuidv7` (default) or `format: uuidv4` |
| `string` | UTF-8 text | `required`, `unique`, `default` |
| `number` | Integer or float | `required`, `default` |
| `boolean` | True/false | `default` |
| `datetime` | ISO 8601 timestamp | `required`, `default` |
| `enum` | One of a fixed set of values | `values: [...]` required; `default` optional |
| `array` | List of items | `items:` sub-schema |
| `object` | Free-form JSON object | none |
| `ref` | Foreign key to another entity | `ref: entityName` required |

## Common field options

- `required: true` -- field must be present on create
- `unique: true` -- value must be unique across all documents (enforced by MongoDB index)
- `default: value` -- server-side default applied when field is omitted

## Create a note with all fields

```bash
curl -X POST http://127.0.0.1:8000/notes \
  -H 'Content-Type: application/json' \
  -d '{
    "title": "My note",
    "body": "Content here",
    "pinned": true,
    "status": "published",
    "publishedAt": "2024-01-15T10:00:00Z",
    "tags": ["tech", "api"],
    "metadata": {"source": "import"}
  }'
```

Fields with defaults (`viewCount`, `pinned`, `status`) can be omitted. The `id` field is always omitted -- it is generated server-side.

**Watch out:** Setting `unique: true` on an optional field means that multiple documents cannot have the same value, including `null`. If the field is omitted, it is stored as absent (not `null`), which avoids this issue. But explicitly sending `null` will trigger the uniqueness constraint.

