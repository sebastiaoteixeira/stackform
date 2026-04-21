# Tutorial 04: Authentication

**Concept introduced:** Auth entities with password-based login and register endpoints.

## Adding a user entity with password auth

Mark an entity with `type: auth` and add an `auth:` block to make it an identity provider.

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
