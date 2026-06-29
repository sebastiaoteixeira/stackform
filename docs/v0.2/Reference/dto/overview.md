---
title: "DTO Definitions"
description: The top-level dto: section declares request-shaped types — fields and validators only, with no persistence — for validating the incoming request body inside access rules.
---

The top-level `dto:` section declares request-shaped types you can validate the
incoming request body against. A DTO is a model stripped of persistence: it has
`fields:` and their validators, and nothing else. It has no id, no repository,
no service, and no storage-only attributes.

DTOs exist so a `when:` rule can validate the request body against a named shape
without forcing that shape to be a stored entity. They are referenced through the
typed request bindings documented in
[when expressions](../when-expressions/overview.md) (for example
`given: { body: request:createMembership }`).

## Syntax

`dto:` is a top-level root, a sibling of `entities:`, `controllers:`, and
`api:`. Each key under it names a DTO; the value is a `fields:` map identical in
shape to an entity's `fields:`:

```yaml
dto:
  createMembership:
    fields:
      role:
        type: enum
        values: [admin, member, viewer]
        required: true
```

The `fields:` block reuses the entity field machinery, so the field options you
already know apply — see [field types](../entities/field-types.md). The
difference is what a DTO is NOT allowed to declare.

## Allowed field types

| Type | Allowed in a DTO |
|------|------------------|
| `string` | yes |
| `number` | yes |
| `boolean` | yes |
| `datetime` | yes |
| `enum` | yes |
| `array` | yes |
| `object` | yes |
| `ref` | yes (target must be a declared entity or DTO) |
| `id` | NO — rejected with `DTO_FORBIDS_PERSISTENCE_ATTR` |

A DTO describes request input, not a stored record, so it has no primary key.
`type: id` is rejected.

## Forbidden persistence attributes

The following attributes are persistence concerns and are rejected anywhere in a
DTO field, failing generation with `DTO_FORBIDS_PERSISTENCE_ATTR`:

| Attribute | Why it is forbidden |
|-----------|---------------------|
| `type: id` | A DTO is request input, not a stored record; it has no primary key. |
| `unique` | Uniqueness is a storage/index concern; a DTO is never persisted. |
| `format` | The persistence/OpenAPI metadata hint has no meaning on a transient request shape. |

Lifecycle attributes that describe the field's behavior rather than storage are
allowed everywhere in a DTO: `default` and `readonly` are accepted.

## Validation timing

When a request binding names a DTO (for example `given: { body: request:createMembership }`),
the request body is validated against that DTO **before** authorization runs. An
invalid body returns 422 and the access rule never executes. See
[when expressions](../when-expressions/overview.md) for the binding forms and the
runtime model.

## Examples

### A DTO for a create body

```yaml
api:
  basePath: /api
  version: v1

dto:
  createMembership:
    fields:
      role:
        type: enum
        values: [admin, member, viewer]
        required: true
      note:
        type: string
        maxLength: 280
```

### A DTO referencing an entity

```yaml
dto:
  assignReviewer:
    fields:
      reviewerId: { type: ref, ref: user, required: true }
      priority:
        type: enum
        values: [low, normal, high]
        default: normal
```

`ref:` may point at a declared entity or another declared DTO. A `ref` whose
target is neither fails generation with `DTO_NOT_FOUND`.

## Edge Cases

- **No id field.** Unlike entities, a DTO must not declare `type: id` and is not
  required to. It is never persisted, so it has no primary key.

- **`format`/`unique` are not silently ignored.** On entities these are
  metadata-only and accepted; inside a DTO they are an error, not a no-op.

- **`ref` target resolution.** A DTO `ref` is resolved against the union of
  declared entity names and declared DTO names. An unknown target is
  `DTO_NOT_FOUND`, not a silent dangling reference.

- **DTOs are request-only.** A DTO never creates a route, a repository, or a
  collection. It exists solely as a named shape for typed request bindings.

## Errors

| Condition | Error code | Message |
|-----------|-----------|---------|
| `type: id`, `unique`, or `format` on a DTO field | `DTO_FORBIDS_PERSISTENCE_ATTR` | "DTO field may not declare persistence attribute '<attr>'" |
| A DTO `ref` whose target is neither a declared entity nor DTO | `DTO_NOT_FOUND` | "DTO '<name>' references unknown type '<target>'" |
| A request binding `:<type>` naming a missing DTO/entity/primitive | `REQUEST_TYPE_NOT_FOUND` | "Request binding type '<type>' is not a primitive, entity, or DTO" |

## See Also

- [Field types](../entities/field-types.md)
- [When expressions](../when-expressions/overview.md)
- [Access control](../controllers/access-control.md)
