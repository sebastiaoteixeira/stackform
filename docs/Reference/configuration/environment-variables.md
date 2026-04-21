---
title: "Reference: Environment Variable Interpolation"
description: Substitutes environment variable values into YAML string values at parse time, before schema validation.
---

Substitutes environment variable values into YAML string values at parse time, before schema validation.

## Syntax

### Required variable

```yaml
uri: ${MONGO_URI}
```

If `MONGO_URI` is not set in the environment, the server fails to start with `INTERPOLATION_MISSING_VAR`.

### Variable with fallback

```yaml
uri: ${MONGO_URI:-mongodb://localhost:27017}
database: ${MONGO_DB:-myapp}
```

If the variable is not set, the fallback value after `:-` is used.

## Behavior

- **Parse time:** Interpolation runs before YAML parsing and schema validation. The `${VAR}` or `${VAR:-default}` patterns are replaced with the resolved value in the raw YAML string.
- **Compile time / Runtime:** No further interpolation occurs. Values are fixed at parse time.

## Options

| Syntax | Behavior |
|--------|----------|
| `${VAR}` | Replaced with the value of `VAR`. Parse error if `VAR` is not set. |
| `${VAR:-default}` | Replaced with the value of `VAR` if set; otherwise uses `default`. |

## Where Interpolation Applies

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

## What is NOT Interpolated

- YAML keys (left-hand side of `:`).
- Boolean and numeric values -- only string values support interpolation.
- Values that are not strings (e.g., `list: true`).

## Runtime Environment Variables

These environment variables are read directly by the runtime, not via YAML interpolation:

| Variable | Default | Description |
|----------|---------|-------------|
| `JWT_SECRET` | `"yaml-api-dev-secret-change-me"` | HMAC key for JWT signing (HS256). |
| `JWT_EXPIRATION_HOURS` | `24` | JWT token lifetime in hours. |

**Warning:** The default `JWT_SECRET` is insecure. Always set it to a strong random value in production.

## Examples

### Development defaults with production override

```yaml
mongo:
  uri: ${MONGO_URI:-mongodb://localhost:27017}
  database: ${MONGO_DB:-myapp}
```

In development, `MONGO_URI` is unset and the fallback is used. In production, `MONGO_URI` is set via the environment.

### Secrets via environment

```yaml
providers:
  google:
    type: oidc
    client_id: ${GOOGLE_CLIENT_ID}
    client_secret: ${GOOGLE_CLIENT_SECRET}
```

Both variables are required (no fallback). The server fails to start if either is missing.

## Edge Cases

- **`${VAR}` with unset variable.** Parse error `INTERPOLATION_MISSING_VAR`. The server does not start.

- **`${VAR:-default}` with empty string.** If `VAR` is set to an empty string, the empty string is used -- NOT the fallback. The fallback only applies when `VAR` is completely unset.

- **Interpolation happens before YAML parsing.** This means `${VAR}` can expand to any YAML value, including numbers, booleans, or complex structures. The expanded string is then parsed as YAML.

- **Nested interpolation.** `${${INNER}}` is NOT supported. The inner `${INNER}` is not resolved first. The entire string is treated as a single variable name reference.

- **Multiple variables in one value.** `${A}/${B}` is supported. Each `${...}` is resolved independently.

## Errors

| Condition | Error code | Message |
|-----------|-----------|---------|
| Required variable not set | `INTERPOLATION_MISSING_VAR` | "Environment variable 'X' is not set" |

The error includes the `path` field indicating where in the spec the unresolved variable was found (e.g., `"mongo.uri"`).

## See Also

- [Auth overview](../auth/overview.md) -- for `JWT_SECRET` and `JWT_EXPIRATION_HOURS`
- [Password provider](../auth/password-provider.md) -- for JWT token configuration
