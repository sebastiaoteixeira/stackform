---
title: "UI Collections"
description: Describes formatted views of entities for display in the frontend.
---

`ui.collections` define presentation-level data models mapped from your backend entities.

They allow you to assemble flat representations from deep relational graphs by pulling fields from related entities.

## Schema

```yaml
ui:
  collections:
    FeedPost:
      fields:
        title: { from: "post.title" }
        authorName: { from: "post.authorId.displayName" }
        date: { from: "post.createdAt", format: "shortDate" }
```

### Fields

Each collection is an object mapping a field name to a definition containing:

| Field | Type | Description |
|-------|------|-------------|
| `from` | string | The entity traversal path: `<entityName>.[refField...].<fieldName>`. Required. |
| `format` | string | Pack-specific format rule (e.g., `date`, `currency`). Optional. |

## Traversal Rules

The `from:` property must follow valid references declared in the backend entities.

If an entity `post` has a reference field `authorId` pointing to entity `user`, which has a string field `displayName`, the UI can access it as:

```yaml
from: "post.authorId.displayName"
```

The pipeline automatically resolves the target data type from the entity schema definition.
