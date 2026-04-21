# Reference: Environment Variable Interpolation

YAML values can reference environment variables using `${VAR}` syntax. Interpolation happens at parse time before the spec is validated.

## Syntax

### Required variable

```yaml
uri: ${MONGO_URI}
```

If `MONGO_URI` is not set, the server fails to start with an `INTERPOLATION_MISSING_VAR` error.

### Variable with fallback

```yaml
uri: ${MONGO_URI:-mongodb://localhost:27017}
database: ${MONGO_DB:-myapp}
```

If the variable is not set, the fallback value after `:-` is used.

## Where interpolation applies

Interpolation works in any string value anywhere in the spec:

```yaml
mongo:
  uri: ${MONGO_URI}
  database: ${MONGO_DB:-myapp}

providers:
  google:
    type: oidc
    client_id: ${GOOGLE_CLIENT_ID}
    client_secret: ${GOOGLE_CLIENT_SECRET}

api:
  basePath: ${API_BASE_PATH:-/api}
```

## What is not interpolated

- YAML keys (left-hand side of `:`)
- Boolean and numeric values — only string values support interpolation
- Values that are not strings (e.g., `list: true`)

## Error behavior

Missing required variables (`${VAR}` without `:-`) produce:

```json
{
  "code": "INTERPOLATION_MISSING_VAR",
  "message": "Environment variable 'MONGO_URI' is not set",
  "path": "mongo.uri"
}
```

## Best practice

Use fallbacks for development defaults, require explicit variables in production:

```yaml
mongo:
  uri: ${MONGO_URI:-mongodb://localhost:27017}   # dev fallback
  database: ${MONGO_DB}                           # required in all environments
```
