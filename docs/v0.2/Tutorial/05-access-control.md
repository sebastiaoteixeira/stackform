---
title: "Tutorial 05: Access Control"
description: Protecting routes with `"*"` (any authenticated user) and per-operation access overrides.
---

**Concept introduced:** Protecting routes with `"*"` (any authenticated user) and per-operation access overrides.

## Restricting write operations

With a user entity in place, restrict note creation, update, and delete to authenticated users only.

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

  notes:
    service: notes
    base_path: /notes
    access: public
    operations:
      create: { access: "*" }
      update: { access: "*" }
      delete: { access: "*" }
```

## How access resolution works

The controller-level `access:` is the default for all operations. Per-operation `access:` overrides the default for that operation only.

| Operation | Effective access | Who can call it |
|-----------|-----------------|-----------------|
| list | public | anyone |
| get | public | anyone |
| create | `"*"` | any authenticated user |
| update | `"*"` | any authenticated user |
| delete | `"*"` | any authenticated user |

## Calling a protected route

**Note:** This example uses `jq` to extract the token from the JSON response. If you don't have `jq` installed, copy the token value manually from the JSON output.

```bash
# Get a token first
TOKEN=$(curl -s -X POST http://127.0.0.1:8000/users/login \
  -H 'Content-Type: application/json' \
  -d '{"email": "alice@example.com", "password": "s3cr3t"}' \
  | jq -r .token)

# Create a note with the token
curl -X POST http://127.0.0.1:8000/notes \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"title": "Protected note"}'
```

## Access values

| Value | Meaning |
|-------|---------|
| `public` | No authentication required |
| `"*"` | Any authenticated principal (any auth entity) |
| `user:*` | Any principal from the `user` entity specifically |
| `user:admin` | User with the `admin` role (requires roles, covered in tutorial 06) |

With only one auth entity, `user:*` and `"*"` are equivalent. The difference matters when you have multiple auth entities (e.g., users and API clients).

**Note:** Per-operation `access:` completely replaces the controller-level default. There is no merging. If the controller has `access: public` and an operation has `access: "*"`, only `"*"` applies to that operation.

