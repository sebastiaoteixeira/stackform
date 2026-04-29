---
title: "UI Views"
description: Defines the page-level routes and their top-level components.
---

The `ui.views` block defines your application's routing map.

## Schema

```yaml
ui:
  views:
    HomePage:
      path: "/"
      component: "FeedView"
      props:
        collection: "FeedPost"
```

| Field | Type | Description |
|-------|------|-------------|
| `path` | string | The client-side route path (e.g., `/posts/{id}`). |
| `component` | string | The top-level component for this route. Can refer to a pack component or a custom one from `ui.components`. |
| `props` | map | Static prop values passed to the root component. |

## Resolving View Components

Views can instantiate components declared in `ui.components`, or instantiate components shipped inherently by the selected pack.
