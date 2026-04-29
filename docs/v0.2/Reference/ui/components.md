---
title: "UI Components"
description: Declares reusable frontend components and their render tree.
---

The `ui.components` block allows developers to declare abstract components constructed from smaller building blocks provided by the chosen generator pack.

## Schema

```yaml
ui:
  components:
    PostCard:
      props:
        post: { required: true }
        showAuthor: { required: false }
      render:
        component: "Card"
        props:
          title: $post.title
          subtitle: $post.authorName
```

### `props`

Defines the variables the component accepts. Keys are prop names, and the value is an object optionally specifying `required: true`.

### `render`

Defines the structure of the component as a `ComponentNode`:

| Field | Type | Description |
|-------|------|-------------|
| `component` | string | Must be a component name provided by the pack. |
| `props` | map | Prop values. Can be references, literals, or nested nodes. |

## Prop Values

- **Literal:** Plain strings, numbers, booleans. (e.g., `title: "Static Text"`)
- **Reference:** Starts with `$` and points to a declared prop (e.g., `title: $post`).
- **Nested Component:** An inline `ComponentNode` object defining a sub-component.

```yaml
render:
  component: Stack
  props:
    direction: "vertical"        # Literal
    content:                     # Nested component
      component: Text
      props:
        value: $post.body        # Reference
```
