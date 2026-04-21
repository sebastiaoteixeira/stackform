---
title: "Reference: API Key Provider"
description: Enables machine-to-machine authentication via a static API key passed in a request header.
---

# Reference: API Key Provider

Enables machine-to-machine authentication via a static API key passed in a request header.

## Syntax

```yaml
entities:
  apiClient:
    type: auth
    auth:
      identifier: clientId
      via: apiKey
    fields:
      id: { type: id }
      clientId: { type: string, required: true, unique: true }
      name: { type: string, required: true }
      active: { type: boolean, default: true }
```

## Behavior

- **Parse time:** The `apiKey` provider is validated. The `identifier` field must exist in `fields:`.
- **Compile time:** Register endpoint is generated for client creation. No separate login endpoint -- the API key itself is the credential on every request.
- **Runtime:** On each request, the engine looks up the client record by matching the provided key against `_auth.apiKey`. On match, a principal is resolved with `sub` set to the primary key value.

## Options

| Field | Required | Type | Description |
|-------|----------|------|-------------|
| `identifier` | yes | string (field name) | The field used as the client's unique identifier. Must be `unique: true`. |

## Authentication Flow

1. The client stores both `clientId` and an API key value.
2. On each request, the client sends the API key in the `X-API-Key` header or as a Bearer token.
3. The engine looks up the client record by matching the provided key against `_auth.apiKey`.
4. On match, a principal is resolved with `sub` set to the primary key value.

## Creating a Client

```json
POST /api-clients
{
  "clientId": "my-service",
  "name": "My Backend Service",
  "apiKey": "sk-abc123..."
}
```

The API key value is stored in `_auth.apiKey` in MongoDB.

## Making Authenticated Requests

```bash
# Via X-API-Key header (preferred)
curl -H "X-API-Key: sk-abc123..." http://localhost:8000/resources

# Via Bearer token
curl -H "Authorization: Bearer sk-abc123..." http://localhost:8000/resources
```

## Generated Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/{base_path}/register` | Create a new client record |
| GET | `/{base_path}` | List clients |
| GET | `/{base_path}/{id}` | Get a client |
| PATCH | `/{base_path}/{id}` | Update a client |
| DELETE | `/{base_path}/{id}` | Delete a client |

There is no separate "login" step for API keys. The key itself is the credential on every request.

## Differences from Password Provider

| Aspect | password | apiKey |
|--------|----------|--------|
| Auth mechanism | Username + password, then JWT | Key on every request |
| Token lifetime | JWT expiry (default 24h) | Indefinite (until revoked/deleted) |
| Primary use case | Human users | Services, scripts, integrations |
| Register endpoint | Yes (creates user) | Yes (creates client record) |
| Login endpoint | Yes (issues JWT) | No separate login step |

## Examples

### API client with tier-based roles

```yaml
entities:
  apiClient:
    type: auth
    auth:
      identifier: clientId
      via: apiKey
    roles:
      values: [free, premium, enterprise]
      default: free
      hierarchy:
        enterprise: [premium]
        premium: [free]
    fields:
      id: { type: id }
      clientId: { type: string, required: true, unique: true }
      name: { type: string, required: true }
```

## Edge Cases

- **API key header precedence.** The `X-API-Key` header is checked first. If absent, the `Authorization: Bearer` header is used.

- **Bearer token collision with JWT.** If the `Authorization: Bearer` value is a valid JWT, it is treated as JWT auth, not API key auth. API keys that happen to look like valid JWTs will not work via the Bearer header. Use the `X-API-Key` header instead.

- **No auto-generation of API keys.** The client must provide the API key value on creation. There is no built-in key generation mechanism.

- **No rotation mechanism.** There is no built-in API key rotation endpoint. To rotate, update the client record with a new `apiKey` value via the update endpoint.

- **API key in responses.** The `_auth.apiKey` field is stored in the `_auth` namespace and is stripped from responses, just like `passwordHash`.

## Errors

| Condition | HTTP Status | Response |
|-----------|-------------|----------|
| Invalid or unknown API key | 401 | Unauthorized |
| Missing API key on protected route | 401 | Unauthorized |

## See Also

- [Auth overview](./overview.md)
- [Password provider](./password-provider.md)
- [Access control](../controllers/access-control.md)
