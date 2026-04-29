---
title: "Tutorial 04: Authentication"
description: Auth entities with password-based login and register endpoints.
---

**Concept introduced:** Auth entities with password-based login and register endpoints.

## Adding a user entity with password auth

Mark an entity with `type: auth` and add an `auth:` block to make it an identity provider.

The `identifier` field tells the engine which field uniquely identifies a user at login time. In this example, `identifier: email` means the user logs in with their email address.

The `via` field tells the engine how the user proves their identity. `via: password` means username/password authentication. The engine automatically adds a `password` field to the register payload -- you do not declare it in `fields:`. The password is hashed before storage and never persisted in plain text.

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

  author:
    fields:
      id: { type: id }
      name: { type: string, required: true }
      bio: { type: string }

  note:
    fields:
      id: { type: id }
      title: { type: string, required: true }
      body: { type: string }
      authorId: { type: ref, ref: author }

repositories:
  users:
    entity: user
  authors:
    entity: author
  notes:
    entity: note

services:
  users: {}
  authors: {}
  notes: {}

controllers:
  users:
    service: users
    base_path: /users
    access: public
    operations:
      register: { access: public }
      login: { access: public }

  authors:
    service: authors
    base_path: /authors
    access: public

  notes:
    service: notes
    base_path: /notes
    access: public
```

## How password auth works

When an entity uses `via: password`, a `password` field is automatically added to the register payload. You do not declare it in `fields:` -- it is implicit. The engine hashes the password and stores it in the `_auth` namespace internally; the raw password is never persisted.

A JWT (JSON Web Token) is a signed string that encodes the user's identity. After login, include it in the `Authorization: Bearer <token>` header on subsequent requests to authenticate. Access control using the token is covered in [Tutorial 05: Access Control](./05-access-control.md).

## Generated auth endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | /users/register | Create a new user (password hashed automatically) |
| POST | /users/login | Authenticate and receive a JWT token |

Standard CRUD endpoints are also generated for `/users`.

## Register and login

```bash
# Register
curl -X POST http://127.0.0.1:8000/users/register \
  -H 'Content-Type: application/json' \
  -d '{"email": "alice@example.com", "displayName": "Alice", "password": "s3cr3t"}'

# Login
curl -X POST http://127.0.0.1:8000/users/login \
  -H 'Content-Type: application/json' \
  -d '{"email": "alice@example.com", "password": "s3cr3t"}'
# Returns: {"token": "eyJ..."}
```

**Watch out:** The default `JWT_SECRET` is an insecure placeholder. Always set the `JWT_SECRET` environment variable to a strong random value before deploying to production.

## Key points

- `type: auth` on an entity enables identity provider behavior.
- The `auth:` block configures authentication. `via: password` enables username/password auth.
- `identifier: email` sets which field is used as the login username.
- Passwords are hashed with PBKDF2-SHA256. The raw password is never stored.
- The `password` field in the register payload is implicit -- you do not declare it in `fields:`.
- The JWT token from `/login` is passed as `Authorization: Bearer <token>` on protected routes.

