# Repository Operations

## Design

A repository operation is one of three kinds:

- **entity** — standard CRUD generated automatically for a given entity
- **query** — a structured MongoDB query using MongoDB shell command names
- **handler** — delegates to user-provided code

`query` and `handler` can coexist. When both are set, the query runs first and its result is passed to the handler.

There is no abstracted query language beyond `entity`. Anything beyond basic CRUD is database-specific by nature.

---

## YAML Schema

```yaml
repositories:
  <name>:
    entity: <entity-name>           # optional
    crud: [list, get, create, update, replace, delete]  # optional, defaults to global defaults
    operations:
      <op-name>:
        query:                      # option 1 — structured MongoDB query
          command: <mongodb-command>
          collection: <name>        # optional, defaults to entity collection
          # ...command-specific fields
        handler: "<dotted.path>"    # option 2 — user-provided function
        # query and handler can coexist
```

### Query commands

`command` uses MongoDB shell naming (camelCase). The generator translates to the Motor method via camelCase → snake_case.

| command | Motor method | required fields |
|---|---|---|
| `find` | `find` | `filter` |
| `findOne` | `find_one` | `filter` |
| `aggregate` | `aggregate` | `pipeline` |
| `countDocuments` | `count_documents` | `filter` |
| `estimatedDocumentCount` | `estimated_document_count` | — |
| `distinct` | `distinct` | `key`, optionally `filter` |
| `insertOne` | `insert_one` | `document` |
| `insertMany` | `insert_many` | `documents` |
| `updateOne` | `update_one` | `filter`, `update` |
| `updateMany` | `update_many` | `filter`, `update` |
| `replaceOne` | `replace_one` | `filter`, `replacement` |
| `deleteOne` | `delete_one` | `filter` |
| `deleteMany` | `delete_many` | `filter` |
| `findOneAndUpdate` | `find_one_and_update` | `filter`, `update` |
| `findOneAndReplace` | `find_one_and_replace` | `filter`, `replacement` |
| `findOneAndDelete` | `find_one_and_delete` | `filter` |
| `bulkWrite` | `bulk_write` | `requests` |

### Rules

- `entity` and `operations` are both optional, but at least one must be present
- `crud` is only valid when `entity` is set — it selects which standard operations to generate (defaults to the global defaults)
- An operation must have at least one of `query` or `handler`
- `collection` inside `query` is optional when the repo has an `entity` — defaults to that entity's collection. Required for operations-only repos.

---

## Examples

### Standard CRUD only

```yaml
repositories:
  posts:
    entity: post
```

### CRUD + custom read operation

```yaml
repositories:
  posts:
    entity: post
    operations:
      posts-by-author:
        query:
          command: find
          filter: { "authorId": "{{params.authorId}}" }
```

### Cross-collection query (aggregation)

```yaml
repositories:
  posts:
    entity: post
    operations:
      posts-with-author:
        query:
          command: aggregate
          pipeline:
            - $match: { "authorId": "{{params.authorId}}" }
            - $lookup: { from: users, localField: authorId, foreignField: _id, as: author }
            - $unwind: "$author"
            - $project: { title: 1, "author.name": 1 }
```

### Write operation

```yaml
repositories:
  posts:
    entity: post
    operations:
      publish:
        query:
          command: findOneAndUpdate
          filter: { "_id": "{{params.id}}" }
          update: { "$set": { "status": "published" } }
```

### Custom operations only (no entity)

```yaml
repositories:
  stats:
    operations:
      avg-posts-per-author:
        query:
          command: aggregate
          collection: posts
          pipeline:
            - $group: { _id: "$authorId", count: { $sum: 1 } }
      send-report:
        handler: stats.send_report
```

### Query + handler together

```yaml
repositories:
  posts:
    entity: post
    operations:
      export-csv:
        query:
          command: find
          filter: { "publishedAt": { "$exists": true } }
        handler: posts.format_as_csv
```

The handler receives the query result as its first argument:
```python
async def format_as_csv(result: list[dict]) -> Any: ...
```

---

## IR

```python
CRUD_OPERATIONS = ("list", "get", "create", "update", "replace", "delete")


@dataclass(frozen=True)
class IROperation:
    name: str
    query: dict | None = None   # structured MongoDB query object
    handler: str | None = None


@dataclass(frozen=True)
class IRRepository:
    name: str
    entity: str | None = None
    crud: tuple[str, ...] = CRUD_OPERATIONS  # only relevant when entity is set
    operations: dict[str, IROperation] = field(default_factory=dict)
```

`IRDocument` gains `repositories: dict[str, IRRepository]`.

`IRCollection` is reduced to entity schema only — no operations field.