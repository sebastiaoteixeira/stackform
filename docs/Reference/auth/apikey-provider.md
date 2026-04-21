# Reference: API Key Provider

The `apiKey` provider enables machine-to-machine authentication via a static API key passed in a request header.

## Configuration

```yaml
entities:
  apiClient:
    type: auth
    via:
      - provider: apiKey
        identifier: clientId
    fields:
      id: { type: id }
      clientId: { type: string, required: true, unique: true }
      name: { type: string, required: true }
      active: { type: boolean, default: true }
```

## `identifier`

The field used as the client's unique identifier. Must be `unique: true`. Commonly `clientId`.

## Authentication flow

1. The client stores both `clientId` and an API key value.
2. On each request, the client sends the API key in the `X-API-Key` header (or as a Bearer token).
3. The engine looks up the client record by matching the provided key.
4. On match, a principal is resolved with `sub` set to the `identifier` field value.

## Creating a client

```json
POST /api-clients
{
  "clientId": "my-service",
  "name": "My Backend Service",
  "apiKey": "sk-abc123..."
}
```

The API key value is stored (hashed or encrypted, depending on config) in `_auth` storage.

## Making authenticated requests

```bash
curl -H "X-API-Key: sk-abc123..." http://localhost:8000/resources

# or as Bearer token:
curl -H "Authorization: Bearer sk-abc123..." http://localhost:8000/resources
```

## Generated endpoints

With `register` and `login` enabled, the engine adds standard CRUD for the entity. There is no separate "login" step for API keys — the key itself is the credential on every request.

## Differences from password provider

| Aspect | password | apiKey |
|--------|----------|--------|
| Auth mechanism | Username + password → JWT | Key on every request |
| Token lifetime | JWT expiry | Indefinite (until revoked) |
| Primary use case | Human users | Services, scripts, integrations |
| Register endpoint | Yes (creates user) | Yes (creates client record) |
| Login endpoint | Yes (issues JWT) | No separate login step |
