---
title: "Repositories Overview"
description: Repositories bind an entity to a MongoDB collection, select which CRUD operations are available, and declare custom query and handler operations.
---

Repositories bind an entity to a MongoDB collection, select which CRUD operations are available, and declare custom operations.

The repository name is the MongoDB collection name. It is free-form (no pluralization is applied) and is what services reference. A repository whose `entity` is `myEntity` and whose key is `myCollection` stores documents in a collection named `myCollection`.

## Structure

```yaml
repositories:
  myCollection:
    entity: myEntity
    crud: [list, get, create, update, delete]   # subset; omit for all six
    operations:                                  # custom ops (optional)
      publishedByOwner:
        query:
          command: find
          filter: { ownerId: $ownerId, status: 'published' }
```

## Fields

### `entity`

Type: string (entity name). Required unless the repository only declares custom `operations`.

The entity this repository stores. Must match a concrete (non-abstract) key in `entities:`. Pointing a repository at an abstract entity is rejected at build time with `DESUGAR_ABSTRACT_REFERENCED`.

### `crud`

Type: list of operation names. Optional.

Selects which built-in CRUD operations this repository exposes. When omitted, all six are enabled. Listing a subset opts the rest out end-to-end: an omitted operation produces no repository method, no service, no HTTP route, no OpenAPI entry, and no UI action.

Valid operation names are `list`, `get`, `create`, `update`, `replace`, `delete`. Any other value is rejected with `CRUD_OPERATION_INVALID`. Specifying `crud` without an `entity` is rejected with `CRUD_WITHOUT_ENTITY`.

For the full enablement model and resolution precedence, see [composable-crud](composable-crud.md).

### `operations`

Type: map. Optional.

Declares custom operations beyond the six built-in CRUD verbs. This block is exclusively for custom operations; it does NOT toggle CRUD on or off (use `crud:` for that). Each entry must define either a `query` or a `handler`; an entry with neither is rejected with `OPERATION_MISSING_QUERY_OR_HANDLER`.

A `query` runs a MongoDB command against the repository's collection:

```yaml
repositories:
  myCollection:
    entity: myEntity
    operations:
      recent:
        query:
          command: find
          filter: { status: 'published' }
          collection: myArchiveCollection   # optional override of the target collection
```

The `command` must be one of: `find`, `findOne`, `aggregate`, `countDocuments`, `estimatedDocumentCount`, `distinct`, `insertOne`, `insertMany`, `updateOne`, `updateMany`, `replaceOne`, `deleteOne`, `deleteMany`, `findOneAndUpdate`, `findOneAndReplace`, `findOneAndDelete`, `bulkWrite`. An unknown command is rejected with `QUERY_COMMAND_UNKNOWN`. Most commands require a specific field (`find`/`findOne`/`updateOne`/`deleteOne`/... require `filter`; `aggregate` requires `pipeline`; `insertOne` requires `document`; `insertMany` requires `documents`; `bulkWrite` requires `requests`); a missing required field is rejected with `QUERY_MISSING_FIELD`.

By default a query targets the repository's collection. If the repository declares no `entity`, the query must set `collection:` explicitly, otherwise the build fails with `QUERY_MISSING_COLLECTION`.

A `handler` names a dotted import path to your own function instead of a Mongo command:

```yaml
repositories:
  myCollection:
    entity: myEntity
    operations:
      rebuildSlugs:
        handler: my_app.maintenance.rebuild_slugs
```

To expose a custom operation over HTTP, reference it from a service and add a controller operation with `method` and `path`. See [services/custom-operations](../services/custom-operations.md).

A repository must carry at least an `entity` or one custom operation; an empty repository is rejected with `REPOSITORY_EMPTY`.

## Default operations

When `crud` is omitted, all six operations are enabled (subject to `api.operations.defaults` and per-service overrides):

| Operation | HTTP method | Description |
|-----------|-------------|-------------|
| `list` | GET | Return all documents |
| `get` | GET | Return one document by ID |
| `create` | POST | Insert a new document |
| `update` | PATCH | Partial update of a document |
| `replace` | PUT | Full replacement of a document |
| `delete` | DELETE | Remove a document by ID |

`replace` (PUT) is enabled by default like the other five; it is not a repository-level opt-in.

## Selecting a subset

To expose only a subset, list it in `crud`. The example below makes `myOtherCollection` read-and-write but never editable (no `update`), so the generated app emits no PATCH route and no Edit action for it:

```yaml
repositories:
  myOtherCollection:
    entity: myOtherEntity
    crud: [create, list, get, delete]
```

## Resolution precedence

The final per-operation decision is resolved in this order, most specific first:

1. A service-level override (`services.<name>.operations.<op>: true | false | {handler}`).
2. The repository `crud` list.
3. `api.operations.defaults` (an OperationFlags object used to disable an op globally, e.g. `{ replace: false }`).
4. All six enabled.

See [operations](operations.md) for service-level overrides and [composable-crud](composable-crud.md) for the full model.

## Example

```yaml
api:
  basePath: /api
  version: v1

repositories:
  users:
    entity: user

  myCollection:
    entity: myEntity
    crud: [list, get, create, update, delete]

  myOtherCollection:
    entity: myOtherEntity
    crud: [create, list, get, delete]
```

Each repository name is independent of the entity name. `users` binds to entity `user`, `myCollection` to `myEntity`, etc. With the `api:` block above, the generated routes live under `/api/v1` (for example `GET /api/v1/myCollection`, `POST /api/v1/myOtherCollection`). The repository name is both the collection name and what controllers and services reference.

## Errors

| Code | Cause |
|------|-------|
| `CRUD_WITHOUT_ENTITY` | `crud` specified but the repository has no `entity`. |
| `CRUD_OPERATION_INVALID` | A name in `crud` is not one of the six CRUD operations. |
| `OPERATION_MISSING_QUERY_OR_HANDLER` | A custom operation declares neither `query` nor `handler`. |
| `QUERY_COMMAND_UNKNOWN` | `query.command` is not a recognized MongoDB command. |
| `QUERY_MISSING_FIELD` | The command requires a field (e.g. `filter`, `pipeline`) that is absent. |
| `QUERY_MISSING_COLLECTION` | A query on an entity-less repository omits `collection`. |
| `REPOSITORY_EMPTY` | A repository declares neither `entity` nor any custom operation. |
| `DESUGAR_ABSTRACT_REFERENCED` | The `entity` names an abstract entity. |
