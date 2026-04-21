# Tutorial 06: Roles

**Concept introduced:** Declaring roles on an auth entity and using role-based access control.

## Adding roles to the user entity

Roles are declared via an `enum` field. The auth entity points to that field with `roles:`.

```yaml
version: "0.2"

mongo:
  uri: mongodb://localhost:27017
  database: myapp

entities:
  user:
    type: auth
    via:
      - provider: password
        identifier: email
    roles: role
    fields:
      id: { type: id }
      email: { type: string, required: true, unique: true }
      displayName: { type: string, required: true }
      role:
        type: enum
        values: [admin, moderator, user]
        default: user

  note:
    fields:
      id: { type: id }
      title: { type: string, required: true }
      body: { type: string }

roles:
  user:
    admin: [moderator]
    moderator: [user]

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

The top-level `roles:` section defines which roles include other roles. This is transitive.

```yaml
roles:
  user:
    admin: [moderator]
    moderator: [user]
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

With multiple auth entities, the prefix is required (covered in later tutorials).

## Key points

- `roles: role` on the entity points to the name of the enum field used for role assignment.
- New users get `default: user` automatically on register.
- Role inheritance is defined separately in top-level `roles:`, not on the entity itself.
- Roles are per-entity — different auth entities can have completely different role sets.
