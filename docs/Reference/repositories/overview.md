---
title: "Reference: Repositories Overview"
description: Repositories bind an entity to a MongoDB collection and define what storage operations are available.
---

# Reference: Repositories Overview

Repositories bind an entity to a MongoDB collection and define what storage operations are available.

## Structure

```yaml
repositories:
  repositoryName:
    entity: entityName
    operations:
      replace: true         # opt-in replace
      customOp:             # custom operation
        base: list
        filter: { authorId: $param.authorId }
```

## Fields

### `entity`

Type: string (entity name). Required.

The entity this repository stores. Must match a non-abstract key in `entities:`.

### `operations`

Type: map. Optional.

Configures built-in operation overrides and declares custom operations.

To opt into `replace` (PUT): `replace: true`.

To define custom operations, see [custom-operations](../services/custom-operations.md) — custom operations declared here are exposed to services.

## Default operations

All repositories support these operations by default (subject to `api.operations.defaults`):

| Operation | HTTP method | Description |
|-----------|-------------|-------------|
| `list` | GET | Return all documents |
| `get` | GET | Return one document by ID |
| `create` | POST | Insert a new document |
| `update` | PATCH | Partial update of a document |
| `replace` | PUT | Full replacement of a document (opt-in) |
| `delete` | DELETE | Remove a document by ID |

## Opt-in replace

`replace` is disabled by default. Enable it per-repository:

```yaml
repositories:
  posts:
    entity: post
    operations:
      replace: true
```

## Example

```yaml
repositories:
  users:
    entity: user

  posts:
    entity: post
    operations:
      replace: true

  countries:
    entity: country
```

Each repository name is independent of the entity name. `users` binds to entity `user`, `posts` to `post`, etc. The repository name is what controllers and services reference.
