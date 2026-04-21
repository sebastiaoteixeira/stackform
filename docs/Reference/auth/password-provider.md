# Reference: Password Provider

The `password` provider enables username/password authentication with secure hashing.

## Configuration

```yaml
entities:
  user:
    type: auth
    via:
      - provider: password
        identifier: email
    fields:
      id: { type: id }
      email: { type: string, required: true, unique: true }
      displayName: { type: string, required: true }
```

## `identifier`

The field used as the login username. Must be declared in `fields:` and should have `unique: true`.

Common values: `email`, `username`, `clientId`.

## Generated endpoints

With `register` and `login` enabled (the default), the engine adds:

| Method | Path | Description |
|--------|------|-------------|
| POST | `/{base_path}/register` | Create a new user with hashed password |
| POST | `/{base_path}/login` | Authenticate and receive a JWT |

## Register request

The `password` field is injected into the register payload automatically. It is not declared in `fields:`.

```json
POST /users/register
{
  "email": "alice@example.com",
  "displayName": "Alice",
  "password": "s3cr3t"
}
```

Response: the created user record (without the password hash).

## Login request

```json
POST /users/login
{
  "email": "alice@example.com",
  "password": "s3cr3t"
}
```

Response:

```json
{
  "token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
}
```

## Token format

The JWT payload includes:

```json
{
  "sub": "alice@example.com",
  "iat": 1700000000,
  "exp": 1700086400
}
```

`sub` is the value of the `identifier` field. Downstream access rules reference it as `principal.sub`.

## Password hashing

Passwords are hashed with PBKDF2-SHA256 at 390,000 rounds. The hash is stored under `_auth.passwordHash` in MongoDB. The raw password is never persisted.

## Using the token

Pass the token as a Bearer token on subsequent requests:

```bash
curl -H "Authorization: Bearer eyJ..." http://localhost:8000/notes
```
