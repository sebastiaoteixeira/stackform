---
title: "Tutorial 03: Relationships"
description: "`type: ref` -- linking entities with foreign key references."
---

**Concept introduced:** `type: ref` -- linking entities with foreign key references.

## Adding an author entity and linking notes

A `ref` field stores the ID of a document in another entity's collection.

```yaml
version: "0.2"

api:
  basePath: /api
  version: v1

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

The `api:` block fixes `basePath: /api` and `version: v1`, so every route is served
under `/api/v1`. `basePath` defaults to `/api` and `version` defaults to empty when
the block is omitted; declaring both keeps the URLs below reproducible.

## What changes

The `note` entity now has `authorId: { type: ref, ref: author }`. This field:

- Stores the `id` value of an `author` document
- Is stored and validated only as a string -- there is no UUID-format check; any
  string is accepted
- Is not automatically joined -- the API returns the raw ID

## Create a note with an author reference

```bash
# First create an author
curl -X POST http://127.0.0.1:8000/api/v1/authors \
  -H 'Content-Type: application/json' \
  -d '{"name": "Alice"}'
# Returns: {"id": "019...", "name": "Alice"}

# Then create a note referencing that author
curl -X POST http://127.0.0.1:8000/api/v1/notes \
  -H 'Content-Type: application/json' \
  -d '{"title": "My note", "authorId": "019..."}'
```

**Watch out:** `ref` fields do NOT enforce referential integrity. MongoDB has no
foreign key constraints, so you can set `authorId` to a non-existent ID without
error. Dangling references are possible if the referenced document is deleted. A bad
`ref:` target is also not caught at generation time for a plain ref field: if you
point `ref:` at an entity that does not exist, the build still succeeds and the field
behaves like any other string. (The only place a `ref:` target is checked is a
`ui.collections` path that traverses through it.)

## Requiring the relationship

Add `required: true` to make the reference mandatory on create:

```yaml
note:
  fields:
    id: { type: id }
    title: { type: string, required: true }
    authorId: { type: ref, ref: author, required: true }
```

Now a `POST /api/v1/notes` without `authorId` is rejected with a validation error.

## Showing relationships in the UI

If your spec has a `ui:` block, the generated React admin renders `ref` fields as a
relation control (a picker bound to the target entity) rather than a plain text input.
The reference is still stored and sent as the raw ID string; the UI only changes how
you select it.

## Key points

- `ref: author` points to the entity name (singular), not the repository or
  collection name.
- `ref` fields are optional by default. Add `required: true` to enforce the
  relationship.
- No cascading deletes or joins are performed automatically.
