# Tutorial 08: Entity Inheritance

**Concept introduced:** Abstract base entities with shared fields, and `extends:` to inherit them.

## Extracting common fields into a base entity

Multiple entities share `id` and `createdAt`. Rather than repeating them, define an abstract base.

```yaml
version: "0.2"

mongo:
  uri: mongodb://localhost:27017
  database: myapp

entities:
  base:
    abstract: true
    fields:
      id: { type: id }
      createdAt: { type: datetime }

  user:
    extends: base
    type: auth
    auth:
      identifier: email
      via: password
    roles:
      values: [admin, moderator, user]
      default: user
      hierarchy:
        admin: [moderator]
        moderator: [user]
    fields:
      email: { type: string, required: true, unique: true }
      displayName: { type: string, required: true }

  note:
    extends: base
    fields:
      title: { type: string, required: true }
      body: { type: string }
      authorId: { type: ref, ref: user }

repositories:
  users:
    entity: user
  notes:
    entity: note

services:
  users: {}
  notes: {}

controllers:
  users:
    service: users
    base_path: /users
    operations:
      register: { access: public }
      login: { access: public }

  notes:
    service: notes
    base_path: /notes
    access: public
    operations:
      create: { access: "*" }
      update:
        access:
          - moderator
          - given:
              principal: identity:user
              document: notes
            when: principal.sub equals document.authorId
      delete:
        access:
          - moderator
          - given:
              principal: identity:user
              document: notes
            when: principal.sub equals document.authorId
```

## How inheritance works

- `extends: base` copies all fields from `base` into the child entity.
- Fields declared in the child entity are merged after inherited fields.
- `abstract: true` marks an entity as a template. Abstract entities are removed after desugaring -- they have no repository, no collection, and cannot be referenced in `ref:` fields.

## What each entity ends up with

After desugaring, `user` has: `id`, `createdAt`, `email`, `displayName`.

After desugaring, `note` has: `id`, `createdAt`, `title`, `body`, `authorId`.

The `base` entity itself is stripped and does not produce a MongoDB collection.

**Watch out:** If the child declares a field with the same name as an inherited field, the child's definition silently overrides the parent's. There is no warning or error. Double-check field names when extending entities.

## Key points

- `abstract: true` prevents a collection from being created for the base entity.
- `extends:` accepts only one parent. There is no multiple inheritance.
- Inheritance also copies `type:` and `auth:` config from the parent, if present. A child can override these.
- Abstract entities can extend other abstract entities.
