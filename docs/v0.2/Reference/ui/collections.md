---
title: "UI Collections"
description: Presentation-level views over your entities, validated and type-resolved at generate time.
---

`ui.collections` declare presentation-level views over your backend entities. Each
collection field maps a display name to a value pulled from an entity, following
declared `ref` fields to reach data on related entities.

Collections are validated and type-resolved when you run `stackform build` (or
`stackform run`): every `from:` path is checked against the entity schema and its
value type is resolved from that schema. They are not a runtime join layer -- the
generated backend does not denormalize or pre-compute collection rows, and the
built-in `generic` pack derives its table columns and detail/form fields from the
entity itself, not from a collection's field list. A collection therefore acts as a
validated, typed contract that views can reference by name; a custom pack is free to
consume the full field map (including `format`).

## Schema

```yaml
ui:
  collections:
    my-feed:
      fields:
        title: { from: myEntity.title }
        content: { from: myEntity.content, format: rich_text }
        ownerName: { from: myEntity.ownerId.displayName }
        status: { from: myEntity.status }
```

### Fields

Each collection has a `fields` map. Each entry maps a display name to a definition:

| Field | Type | Description |
|-------|------|-------------|
| `from` | string | Entity traversal path `<entityName>.[refField...].<fieldName>`. Required. |
| `format` | string | Free-form, pack-interpreted hint (for example `rich_text`). Optional. |

`format` is passed through verbatim to the pack and is not validated against a
fixed set of values. The built-in `generic` pack ignores it; a custom pack that
inspects the collection field map can act on it.

## Traversal Rules

The first segment of `from:` is the entity name (the key under `entities:`), not the
repository or resource name. The remaining segments are field names. The resolved
value type is read from the entity schema.

```yaml
from: "myEntity.ownerId.displayName"
```

Here `myEntity` is the entity. `ownerId` is a `ref` field on `myEntity` pointing at
the `myOtherEntity` entity, and `displayName` is a string field on `myOtherEntity`.

A `ref` field is followed only when it is NOT the final segment. When a `ref` field
is the last segment, its stored value (the referenced id string) is used as-is rather
than being expanded. Fields of type `id` are not part of a collection's traversable
fields, so a path cannot pass through or end on an id field.

## Validation

Paths are checked at generate time. A bad path aborts the build with one of these
messages (exit 1):

| Condition | Message |
|-----------|---------|
| Missing `from` | `Collection '<col>' field '<field>' missing 'from' path` |
| Unknown entity (first segment) | `Collection '<col>' field '<field>': unknown entity '<entity>'` |
| Unknown field on the entity | `Collection '<col>' field '<field>': entity '<entity>' has no field '<segment>'` |
| `ref` points at an unknown entity | `Collection '<col>' field '<field>': ref field '<segment>' points to unknown entity '<ref>'` |

## Using a collection in a view

A view references a collection by name through a `collection:` prop. Use the bare
name to bind a list of records, or append `[id]` to bind a single record resolved
from the `:id` route param.

```yaml
api:
  basePath: /api
  version: v1

ui:
  collections:
    my-feed:
      fields:
        title: { from: myEntity.title }
        content: { from: myEntity.content, format: rich_text }
        ownerName: { from: myEntity.ownerId.displayName }
        status: { from: myEntity.status }

  views:
    my-collection-list:
      path: /my-collection
      component: list-table
      props:
        collection: my-feed
    read-my-entity:
      path: /my-collection/:id
      component: detail-two-column
      props:
        collection: my-feed[id]
```

The list view loads records from `GET /api/v1/my-collection`; the detail view loads a
single record from `GET /api/v1/my-collection/{id}`. The `[id]` suffix selects
single-record binding and does not change the resolved collection name.

## See Also

- [Views](views.md) -- declaring pages that bind a collection.
- [Components](components.md) -- the pack components a view renders.
- [UI Overview](overview.md) -- the `ui:` block and the `generic` pack.
