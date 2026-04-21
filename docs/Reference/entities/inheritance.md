---
title: "Reference: Entity Inheritance"
description: Copies fields and configuration from a parent entity into a child entity via `extends:`.
---

# Reference: Entity Inheritance

Copies fields and configuration from a parent entity into a child entity via `extends:`.

## Syntax

```yaml
entities:
  parentName:
    fields:
      fieldA: { type: string }

  childName:
    extends: parentName
    fields:
      fieldB: { type: string }
```

After desugaring, `childName` has both `fieldA` and `fieldB`.

## Behavior

- **Parse time (desugaring):** The `extends:` reference is resolved. The parent's fields are merged into the child. Inherited fields appear before the child's own fields in the resolved field map. The `extends:` key is stripped from the entity after resolution.
- **Compile time:** The child entity is treated as a fully standalone entity with the merged field set. The parent is not referenced further.
- **Runtime:** No distinction between inherited and declared fields. All fields are treated identically.

## Options

| Property | Required | Type | Description |
|----------|----------|------|-------------|
| `extends` | no | string (entity name) | The parent entity name. Must exist in the same `entities:` section. |
| `abstract` | no | boolean | If `true`, marks the entity as a template-only. Not inherited by children. |

## Inheritance Rules

- `extends:` accepts exactly one parent entity name. Multiple inheritance is not supported.
- The parent may be abstract or concrete.
- Inherited fields appear before the child's own fields in the resolved schema.
- A child field with the same name as an inherited field overrides the inherited definition completely. No merge occurs and no error is raised.
- `type:` (e.g., `type: auth`) is inherited from the parent if the child does not declare its own.
- `auth:` configuration is inherited (deep-copied) from the parent if the child does not declare its own.
- `abstract:` is NOT inherited. A child of an abstract entity is not abstract unless it also declares `abstract: true`.

## `abstract: true`

Marks an entity as a template. Abstract entities:

- Do not produce a MongoDB collection.
- Cannot be bound to a repository.
- Cannot appear as the target of a `ref:` field.
- Are removed from the processed IR before route generation.

## Examples

### Basic inheritance

```yaml
entities:
  base:
    abstract: true
    fields:
      id: { type: id }
      createdAt: { type: datetime }

  post:
    extends: base
    fields:
      title: { type: string, required: true }
```

After desugaring, `post` has: `id`, `createdAt`, `title`.

### Multi-level inheritance (chaining)

```yaml
entities:
  timestamped:
    abstract: true
    fields:
      createdAt: { type: datetime }
      updatedAt: { type: datetime }

  identified:
    abstract: true
    extends: timestamped
    fields:
      id: { type: id }

  user:
    extends: identified
    fields:
      email: { type: string, required: true }
```

`user` ends up with: `createdAt`, `updatedAt`, `id`, `email`. All fields from the full chain are inherited.

### Auth inheritance

```yaml
entities:
  base:
    abstract: true
    type: auth
    auth:
      identifier: email
      via: password
    fields:
      id: { type: id }
      email: { type: string, required: true, unique: true }

  admin:
    extends: base
    fields:
      level: { type: number, default: 1 }
```

After desugaring, `admin` has `type: auth` and the `auth:` config from `base`, plus fields `id`, `email`, `level`.

### Field override

```yaml
entities:
  base:
    abstract: true
    fields:
      id: { type: id }
      name: { type: string }

  user:
    extends: base
    fields:
      name: { type: string, required: true, unique: true }
```

The child's `name` field completely replaces the parent's. `user` has `id` and `name` (required, unique).

## Edge Cases

- **Same-name field override.** If the parent and child both declare a field with the same name, the child's definition wins. No merge occurs and no error is raised.

- **Abstract entities cannot be referenced by repositories.** If a repository's `entity:` points to an abstract entity, the parser raises `DESUGAR_ABSTRACT_REFERENCED`.

- **Circular inheritance.** If `a extends b` and `b extends a` (directly or transitively), the parser raises `ENTITY_CIRCULAR_EXTENDS`.

- **Multi-level inheritance.** Inheritance chains of arbitrary depth are supported. `c extends b, b extends a` results in `c` having all fields from `a`, `b`, and `c`.

- **`type: auth` is inherited.** If the parent is `type: auth`, the child inherits that type. The child may override it by declaring its own `type:`.

- **`auth:` config is inherited.** If the parent has an `auth:` block and the child does not declare one, the child uses a deep copy of the parent's `auth:` config.

- **`abstract:` is NOT inherited.** A child of an abstract entity is concrete by default. The child must explicitly declare `abstract: true` to be abstract.

## Errors

| Condition | Error code | Message |
|-----------|-----------|---------|
| `extends:` references unknown entity | `ENTITY_EXTENDS_NOT_FOUND` | "Entity 'X' extends unknown entity 'Y'" |
| Circular inheritance detected | `ENTITY_CIRCULAR_EXTENDS` | "Circular inheritance detected involving entity 'X'" |
| Repository references abstract entity | `DESUGAR_ABSTRACT_REFERENCED` | "Repository 'X' references abstract entity 'Y'" |

## See Also

- [Entities overview](./overview.md)
- [Field types](./field-types.md)
- [Primary keys](./primary-keys.md)
