---
title: "Entity Inheritance"
description: Copies fields, type, and auth configuration from a parent entity into a child entity via extends.
---

Copies fields, `type`, and `auth` configuration from a parent entity into a child entity via `extends:`.

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

After inheritance is resolved, `childName` has both `fieldA` and `fieldB`.

## Behavior

Inheritance is flattened at parse time, before any code is generated:

- The `extends:` reference is resolved and the parent's `fields` are merged into the child. Inherited fields appear before the child's own fields in the resolved field map. The `extends:` key is then stripped from the entity.
- Each concrete (non-abstract) child becomes an independent entity with the merged field set. The parent is not referenced afterward, and the child backs its own collection.
- At runtime there is no distinction between inherited and declared fields. All fields are treated identically.

Inheritance is resolved parent-first along the chain, so a grandparent's fields are merged before a parent's, and the parent's before the child's.

## Options

| Property | Required | Type | Description |
|----------|----------|------|-------------|
| `extends` | no | string (entity name) | The parent entity name. Must exist in the same `entities:` section. |
| `abstract` | no | boolean | If `true`, marks the entity as template-only. It produces no collection and is removed before generation. |

## Inheritance Rules

- `extends:` accepts exactly one parent entity name. Multiple inheritance is not supported.
- The parent may be abstract or concrete. An abstract entity may itself `extends:` another abstract entity.
- A child may omit `fields:` entirely; it then inherits the parent's fields unchanged.
- Inherited fields appear before the child's own fields in the resolved schema.
- A child field with the same name as an inherited field overrides the inherited definition completely. No merge occurs and no error is raised.
- `type:` (for example `type: auth`) is inherited from the parent if the child does not declare its own.
- `auth:` configuration is inherited (deep-copied) from the parent if the child does not declare its own.
- `abstract:` is NOT inherited. A child of an abstract entity is concrete unless it also declares `abstract: true`.

## What is inherited

`extends:` is not limited to fields. Three things flow from parent to child:

- `fields` are always merged (parent fields first, then the child's).
- `type` is copied only when the child does not declare its own.
- `auth` is copied (as a deep copy) only when the child does not declare its own.

This lets you define an abstract `type: auth` base with a shared `auth:` block and extend it into a concrete identity entity. See [Authentication overview](../auth/overview.md) for the `auth:` block, including `auth.roles: <enumFieldName>` for role-based access.

## `abstract: true`

Marks an entity as a template. Abstract entities:

- Do not produce a collection.
- Cannot be bound to a repository (a repository's `entity:` pointing at an abstract entity raises `DESUGAR_ABSTRACT_REFERENCED`).
- Are removed before route generation.

A field with `type: ref` may name an abstract entity as its target; `ref:` must only name a declared entity (`REF_TARGET_NOT_FOUND`). Only repository `entity:` bindings reject abstract entities.

## Primary key requirement

The id-field requirement applies to the resolved concrete entity, after inheritance is flattened, and only when the entity is bound to a repository. The merged field set must contain exactly one `type: id` field, or the entity must declare a natural `pk:` (see [Primary keys](./primary-keys.md)). An inherited id field counts. A concrete child that neither declares nor inherits an id field, and has no `pk:`, fails with `ID_FIELD_MISSING`. Abstract entities are never checked, because they back no repository.

## Examples

### Basic inheritance

```yaml
entities:
  base:
    abstract: true
    fields:
      id: { type: id }
      createdAt: { type: datetime }

  myEntity:
    extends: base
    fields:
      title: { type: string, required: true }
```

After resolution, `myEntity` has: `id`, `createdAt`, `title`. The id field is inherited, so `myEntity` satisfies the primary-key requirement on its own.

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

`user` ends up with: `createdAt`, `updatedAt`, `id`, `email`. The full chain is resolved parent-first, and both `timestamped` and `identified` are abstract templates that produce no collection.

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

After resolution, `admin` has `type: auth` and the `auth:` config from `base`, plus fields `id`, `email`, `level`. Because `admin` declares neither `type:` nor `auth:`, both are inherited.

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

- **Child without fields.** A child may use `extends:` and omit `fields:` entirely; it inherits the parent's fields verbatim.

- **Abstract extends abstract.** An abstract entity may extend another abstract entity to build a layered template chain.

- **Abstract entities cannot be referenced by repositories.** If a repository's `entity:` points to an abstract entity, the parser raises `DESUGAR_ABSTRACT_REFERENCED`.

- **Abstract `ref:` targets.** A `type: ref` field may name an abstract entity. A name that is not a declared entity raises `REF_TARGET_NOT_FOUND`.

- **Circular inheritance.** If `a extends b` and `b extends a` (directly or transitively), the parser raises `ENTITY_CIRCULAR_EXTENDS`.

- **Multi-level inheritance.** Inheritance chains of arbitrary depth are supported. With `c extends b` and `b extends a`, `c` has all fields from `a`, `b`, and `c`.

## Errors

| Condition | Error code | Message |
|-----------|-----------|---------|
| `extends:` references unknown entity | `ENTITY_EXTENDS_NOT_FOUND` | "Entity 'X' extends unknown entity 'Y'" |
| Circular inheritance detected | `ENTITY_CIRCULAR_EXTENDS` | "Circular inheritance detected involving entity 'X'" |
| Repository references abstract entity | `DESUGAR_ABSTRACT_REFERENCED` | "Repository 'X' references abstract entity 'Y'" |
| Resolved concrete entity has no `type: id` field and no `pk:` | `ID_FIELD_MISSING` | "Entity must define exactly one field with type 'id'" |
| `pk:` names a field not present in the resolved fields | `PK_FIELD_NOT_FOUND` | "pk field 'X' not found in entity 'Y'" |

## See Also

- [Entities overview](./overview.md)
- [Field types](./field-types.md)
- [Primary keys](./primary-keys.md)
- [Authentication overview](../auth/overview.md)
