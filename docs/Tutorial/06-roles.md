---
title: "Tutorial 06: Roles"
description: Declaring roles on an auth entity and using role-based access control.
---

# Tutorial 06: Roles

**Concept introduced:** Declaring roles on an auth entity and using role-based access control.

## Adding roles to the user entity

Roles are declared in a standalone `roles:` block on the entity, as a sibling to `auth:` and `fields:`. The `roles:` block defines the valid role values, a default role, and an optional hierarchy.

```yaml
version: "0.2"

mongo:
  uri: mongodb://localhost:27017
  database: myapp

entities:
  user:
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
      id: { type: id }
      email: { type: string, required: true, unique: true }
      displayName: { type: string, required: true }

  note:
    fields:
      id: { type: id }
      title: { type: string, required: true }
      body: { type: string }

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
      list: { access: admin }
      delete: { access: admin }

  notes:
    service: notes
    base_path: /notes
    access: public
    operations:
      create: { access: "*" }
      update: { access: moderator }
      delete: { access: moderator }
```

## Role hierarchy

The `hierarchy` inside the `roles:` block defines which roles include other roles. This is transitive.

```yaml
roles:
  values: [admin, moderator, user]
  default: user
  hierarchy:
    admin: [moderator]    # admin users inherit moderator permissions
    moderator: [user]     # moderator users inherit user permissions
```

The hierarchy flows from higher privilege to lower:

```text
admin  (highest privilege)
  includes moderator
    includes user  (lowest privilege)
```

- `admin` includes `moderator`, `moderator` includes `user`
- A request with `access: moderator` allows both `moderator` and `admin` users
- `admin` users pass `access: user`, `access: moderator`, and `access: admin` checks

## Single auth entity: prefix is optional

When there is only one auth entity, you can omit the entity prefix in access rules:

```yaml
access: moderator       # same as access: user:moderator
access: admin           # same as access: user:admin
```

With multiple auth entities, the prefix is required. When you have both `user` and `apiClient` entities that each define an `admin` role, writing `access: admin` is ambiguous -- the engine does not know which entity you mean. `user:admin` eliminates the ambiguity. This is covered in later tutorials.

**Watch out:** There is currently no built-in endpoint for changing a user's role. New users always get the `default` role. To change a user's role, you must update the record directly in MongoDB.

## Key points

- The `roles:` block is a standalone section on the entity (sibling to `auth:` and `fields:`).
- It declares `values`, `default`, and optionally `hierarchy`. Roles are not a regular field in `fields:`.
- New users get the `default` role automatically on register.
- Role hierarchy is defined inside the entity's `roles:` block, not at the top level.
- Roles are per-entity -- different auth entities can have completely different role sets.

---

[Previous: Access Control](./05-access-control.md) | [Next: ABAC Rules](./07-abac-rules.md)
