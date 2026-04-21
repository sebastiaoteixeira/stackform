# Reference: Entity Inheritance

## `extends:`

Copies all fields from a parent entity into the child entity.

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

## Rules

- `extends:` accepts one parent entity name. Multiple inheritance is not supported.
- The parent can be abstract or concrete.
- Inherited fields appear before the child's own fields in the resolved schema.
- A child field with the same name as an inherited field overrides the inherited definition.
- `type:` (e.g., `type: auth`), `via:`, and `roles:` are also inherited and can be overridden by the child.
- `abstract:` is not inherited — a child of an abstract entity is not abstract unless it also declares `abstract: true`.

## `abstract: true`

Marks an entity as a template. Abstract entities:

- Do not produce a MongoDB collection.
- Cannot be bound to a repository.
- Cannot appear as the target of a `ref:` field.
- Are removed from the processed IR before route generation.

## Chaining

Abstract entities can extend other abstract entities:

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

`user` ends up with: `createdAt`, `updatedAt`, `id`, `email`.

## Example: shared base across all entities

```yaml
entities:
  base:
    abstract: true
    fields:
      id: { type: id }
      createdAt: { type: datetime }

  user:
    extends: base
    type: auth
    via:
      - provider: password
        identifier: email
    fields:
      email: { type: string, required: true, unique: true }

  post:
    extends: base
    fields:
      title: { type: string, required: true }
      authorId: { type: ref, ref: user }
```
