---
title: "Tutorial 03: Relationships"
description: "`type: ref` -- linking entities with foreign key references."
---

**Concept introduced:** `type: ref` -- linking entities with foreign key references.

## Adding an author entity and linking posts

A `ref` field stores the ID of a document in another entity's collection.

```yaml
version: "0.2"

mongo:
  uri: mongodb://localhost:27017
  database: myapp

entities:
  author:
    fields:
      id: { type: id }
      name: { type: string, required: true }
      bio: { type: string }

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
      authorId: { type: ref, ref: author }

repositories:
  authors:
    entity: author
  notes:
    entity: note

services:
  authors: {}
  notes: {}

controllers:
  authors:
    service: authors
    base_path: /authors
    access: public

  notes:
    service: notes
    base_path: /notes
    access: public
```

## What changes

The `note` entity now has `authorId: { type: ref, ref: author }`. This field:

- Stores the `id` value of an `author` document
- Is validated at the type level (must be a string matching UUID format)
- Is not automatically joined -- the API returns the raw ID

## Create a note with an author reference

```bash
# First create an author
curl -X POST http://127.0.0.1:8000/authors \
  -H 'Content-Type: application/json' \
  -d '{"name": "Alice"}'
# Returns: {"id": "019...", "name": "Alice"}

# Then create a note referencing that author
curl -X POST http://127.0.0.1:8000/notes \
  -H 'Content-Type: application/json' \
  -d '{"title": "My note", "authorId": "019..."}'
```

**Watch out:** `ref` fields do NOT enforce referential integrity. MongoDB has no foreign key constraints, so you can set `authorId` to a non-existent ID without error. Dangling references are possible if the referenced document is deleted.

## Key points

- `ref: author` points to the entity name (singular), not the repository or collection name.
- `ref` fields are optional by default. Add `required: true` to enforce the relationship.
- No cascading deletes or joins are performed automatically.

---

[Previous: Field Types](./02-field-types.md) | [Next: Authentication](./04-authentication.md)
