# Tutorial 09: Custom Operations

**Concept introduced:** Custom service operations with handler functions (e.g., publishing a note).

## Adding a publish operation

Standard CRUD covers most cases. Custom operations handle domain-specific actions that don't map to a simple create/update/delete.

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
      published: { type: boolean, default: false }
      publishedAt: { type: datetime }

repositories:
  users:
    entity: user
  notes:
    entity: note

services:
  users: {}
  notes:
    operations:
      publish: { handler: notes.publish }

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
      publish:
        method: POST
        path: "/{id}/publish"
        access:
          - moderator
          - given:
              principal: identity:user
              document: notes
            when: principal.sub equals document.authorId
```

## The handler function

The `handler: notes.publish` value points to a Python module path. The handler receives the request context and can run arbitrary logic.

```python
# myapp/handlers/notes.py
async def publish(context):
    doc = await context.repository.get(context.params["id"])
    if doc["published"]:
        raise ValueError("Already published")
    return await context.repository.update(
        context.params["id"],
        {"published": True, "publishedAt": context.now()}
    )
```

## Wiring the import

Custom handler modules must be registered in the spec:

```yaml
imports:
  notes: myapp.handlers.notes
```

Add this at the top level of your YAML file (after `version:`).

## What the custom operation generates

| Method | Path | Description |
|--------|------|-------------|
| POST | /notes/{id}/publish | Custom publish handler |

The `method:` and `path:` on the controller operation override the defaults. Without them, the engine infers from the operation name.

**Note:** Custom operations must specify both `method:` and `path:` in the controller. Unlike CRUD operations (`list`, `get`, `create`, `update`, `delete`), custom operations have no default HTTP method or path convention.

## Key points

- `handler:` in a service operation points to `<import_key>.<function_name>`.
- The `imports:` section maps keys to Python module paths.
- Custom operations participate in the same access control system as CRUD operations.
- Standard operations (`list`, `get`, `create`, `update`, `delete`) do not need handlers -- they are built-in.
