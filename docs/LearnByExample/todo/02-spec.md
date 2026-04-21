# Todo App: Full Spec

```yaml
version: "0.2"

mongo:
  uri: ${MONGO_URI:-mongodb://localhost:27017}
  database: ${MONGO_DB:-todo}

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
    fields:
      email: { type: string, required: true, unique: true }
      displayName: { type: string, required: true }

  list:
    extends: base
    fields:
      name: { type: string, required: true }
      ownerId: { type: ref, ref: user, required: true }

  item:
    extends: base
    fields:
      text: { type: string, required: true }
      done: { type: boolean, default: false }
      doneAt: { type: datetime }
      listId: { type: ref, ref: list, required: true }
      # Denormalized for direct ownership checks without a join
      ownerId: { type: ref, ref: user, required: true }

repositories:
  users:
    entity: user
  lists:
    entity: list
  items:
    entity: item

services:
  users: {}
  lists: {}
  items: {}

controllers:
  users:
    service: users
    base_path: /users
    operations:
      register: { access: public }
      login: { access: public }
      # No list, get, or update endpoints — users manage themselves via register/login only

  lists:
    service: lists
    base_path: /lists
    access: "*"
    operations:
      list:
        access:
          - given:
              principal: identity:user
              document: lists
            when: principal.sub equals document.ownerId
      get:
        access:
          - given:
              principal: identity:user
              document: lists
            when: principal.sub equals document.ownerId
      update:
        access:
          - given:
              principal: identity:user
              document: lists
            when: principal.sub equals document.ownerId
      delete:
        access:
          - given:
              principal: identity:user
              document: lists
            when: principal.sub equals document.ownerId

  items:
    service: items
    base_path: /items
    access: "*"
    operations:
      list:
        access:
          - given:
              principal: identity:user
              document: items
            when: principal.sub equals document.ownerId
      get:
        access:
          - given:
              principal: identity:user
              document: items
            when: principal.sub equals document.ownerId
      update:
        access:
          - given:
              principal: identity:user
              document: items
            when: principal.sub equals document.ownerId
      delete:
        access:
          - given:
              principal: identity:user
              document: items
            when: principal.sub equals document.ownerId
```

## Notes on this spec

**Denormalized `ownerId` on items:** Items store both `listId` (for grouping) and `ownerId` (for direct access checks). This avoids a two-step lookup (item → list → owner) during authorization.

**`list` operation with document filter:** The `list` operation applies access rules per-document. All returned documents must pass the `when` condition. This means a `GET /lists` only returns lists owned by the authenticated user.

**No admin role:** This app has no privileged roles. All access is strictly ownership-based. To add admin access later, add a `roles:` block to the user entity with `values`, `default`, and optionally `hierarchy`, then prepend `- admin` to each access list.

**Creating items:** The client must send `ownerId` matching their own `sub`. The server does not auto-fill `ownerId` from the principal — the client is responsible for setting it correctly when creating items and lists.
