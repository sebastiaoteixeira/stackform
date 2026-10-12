---
title: "Tutorial 08: Entity Inheritance"
description: Abstract base entities with shared fields, and `extends:` to inherit them.
---

**Concept introduced:** Abstract base entities with shared fields, and `extends:` to inherit them.

When multiple entities share common fields like `id` and `createdAt`, an abstract base entity avoids repeating them on each entity. This is optional -- you can declare the fields on each entity instead -- but it reduces duplication and keeps specs consistent as they grow.

## Extracting common fields into a base entity

Multiple entities share `id` and `createdAt`. Rather than repeating them, define an abstract base. This spec also shows roles and access rules, so it carries an explicit `api:` block; with `basePath: /api` and `version: v1`, every route is served under `/api/v1`.

```yaml
version: "0.2"

api:
  basePath: /api
  version: v1
  operations:
    auth:
      register: true
      login: true

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
      roles: role
    fields:
      email: { type: string, required: true, unique: true }
      displayName: { type: string, required: true }
      role:
        type: enum
        values: [admin, moderator, user]
        default: user

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

The `user` entity gets its roles from the enum `role` field, wired with `auth.roles: role`. This is the only role mechanism the v0.2 transformer reads. A standalone entity-level `roles: { values, default, hierarchy }` block is accepted by the schema but silently ignored; do not rely on it.

> **Enforcement status**
>
> Roles (exact match), `<entity>:*` scoping, and ownership/ABAC `when` rules
> are enforced by the generated FastAPI backend, the generated DRF backend, and the
> `stackform run` dev server alike. A request that fails a rule gets 401 (missing or
> invalid credentials), 403 (authenticated but not allowed), or 404 (record not
> found, checked before ownership). Two current limitations: role hierarchy (for
> example `admin` inheriting `moderator`) is accepted in YAML but not yet applied
> during enforcement -- only exact role matches are checked; and conditional or
> ownership rules require a v0.2 spec, because v0.1 specs do not parse `when` rules.

## How inheritance works

- `extends: base` copies all fields from `base` into the child entity.
- Fields declared in the child entity are merged after inherited fields.
- `type:` and `auth:` are inherited too, if the parent declares them and the child does not; the child can override either.
- `abstract: true` marks an entity as a template. Abstract entities are removed after inheritance is resolved -- they have no repository and no MongoDB collection.

A child that only adds an `extends:` and overrides config (like `type`/`auth`) may omit `fields:` entirely; it still inherits the parent's fields.

## What each entity ends up with

After inheritance is resolved, `user` has: `id`, `createdAt`, `email`, `displayName`, `role`.

After inheritance is resolved, `note` has: `id`, `createdAt`, `title`, `body`, `authorId`.

The `base` entity itself is stripped and does not produce a MongoDB collection.

**Watch out:** If the child declares a field with the same name as an inherited field, the child's definition silently overrides the parent's. There is no warning or error. Double-check field names when extending entities.

### Multi-level inheritance

`extends:` accepts only one parent (no multiple inheritance), but chains are allowed: an abstract entity can extend another abstract entity. Inheritance is resolved parent-first, so a grandparent's fields reach the grandchild. A cycle (A extends B extends A) is rejected with `ENTITY_CIRCULAR_EXTENDS`.

## Natural primary keys with `pk:`

By default, every entity needs exactly one field with `type: id`, and the server generates a uuidv7 value for it. For entities where a natural identifier already exists (like ISO country codes or currency codes), you can use `pk:` instead to point at one of your own fields.

```yaml
entities:
  country:
    pk: code
    fields:
      code: { type: string }
      name: { type: string, required: true }
```

Why use a natural PK:

- The identifier is already well-known and stable (e.g., `US`, `EUR`, `en-US`).
- Clients can construct URLs directly (`GET /api/v1/countries/US`) without needing to look up a UUID first.

When `pk: code` is set, the URL path parameter uses the pk field value: `GET /api/v1/countries/US` instead of `GET /api/v1/countries/019...`. Because the value is not server-generated, the client must supply the pk field on create.

When `pk:` is declared, the entity's id field (if any) is simply not processed -- the pk field becomes the identifier instead. Declaring both `pk:` and a `type: id` field is not validated or rejected, but the `id` field is ignored, so do not declare both.

## Errors you may hit

| Code | Cause |
| --- | --- |
| `ENTITY_EXTENDS_NOT_FOUND` | `extends:` names an entity that does not exist. |
| `ENTITY_CIRCULAR_EXTENDS` | An inheritance chain forms a cycle. |
| `DESUGAR_ABSTRACT_REFERENCED` | A repository's `entity:` points at an abstract entity. |
| `PK_FIELD_NOT_FOUND` | `pk:` names a field the entity does not declare. |
| `ID_FIELD_MISSING` | A non-`pk:` entity has no `type: id` field. |
| `ID_FIELD_MULTIPLE` | An entity declares more than one `type: id` field. |
| `AUTH_ROLES_FIELD_NOT_FOUND` / `AUTH_ROLES_FIELD_NOT_ENUM` | `auth.roles` names a missing field, or one that is not `type: enum`. |

## Key points

- `abstract: true` prevents a collection from being created for the base entity.
- Only a repository binding (`repositories.<name>.entity`) to an abstract entity is checked (`DESUGAR_ABSTRACT_REFERENCED`); a `ref:` field pointing at an abstract entity is not validated, since plain `ref:` targets are never checked at generation time.
- `extends:` accepts only one parent. There is no multiple inheritance, but chains of abstract entities are allowed.
- Inheritance also copies `type:` and `auth:` config from the parent, if present. A child can override these.
- Roles come from an enum field wired with `auth.roles: <fieldName>`, not from a standalone entity-level `roles:` block (which is inert).
- `pk:` lets you use a natural key (like a country code) instead of an auto-generated UUID; the client supplies it on create.
