---
title: "Reference: Repository Operations"
---

# Reference: Repository Operations

## Built-in operations

| Operation | Default | HTTP | Description |
|-----------|---------|------|-------------|
| `list` | on | GET | List all documents. Supports filtering and pagination. |
| `get` | on | GET | Retrieve one document by primary key. |
| `create` | on | POST | Insert a new document. Auto-generates `id` (or `pk` field). |
| `update` | on | PATCH | Partial update. Only supplied fields are modified. |
| `replace` | off | PUT | Full replacement. All fields must be supplied. |
| `delete` | on | DELETE | Remove a document by primary key. |

Default behavior is controlled by `api.operations.defaults` in the spec. Repository-level settings override the global defaults for that repository only.

## Enabling replace

`replace` is `false` by default everywhere. To enable it for a specific repository:

```yaml
repositories:
  posts:
    entity: post
    operations:
      replace: true
```

## Disabling operations

To disable a built-in operation for a specific repository, set it to `false`:

```yaml
repositories:
  users:
    entity: user
    operations:
      delete: false    # prevent deletion via this repository
```

Note: disabling at the repository level prevents the operation from being available to any service or controller. This is a hard block, not just an access control restriction.

## Custom operations

Custom operations are declared in the repository and expose parameterized queries or logic to services:

```yaml
repositories:
  posts:
    entity: post
    operations:
      by-author:
        base: list
        filter: { authorId: $param.authorId }
```

`base:` specifies which built-in operation this extends. `filter:` adds a fixed filter to the query. `$param.fieldName` substitutes a value from the route parameters or request body.

Custom operations declared in repositories must be wired up through a service before being callable from a controller. Controllers cannot reference repository operations directly.

## Relationship to services

Services reference repository operations by name:

```yaml
services:
  list-posts:  { repository: posts, operation: list }
  by-author:   { repository: posts, operation: by-author }
```

Only operations explicitly exposed through a service are callable from controllers.
