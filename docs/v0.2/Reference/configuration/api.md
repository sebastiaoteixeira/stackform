---
title: "`api:`"
description: The `api:` section controls global API settings, URL prefixes, and default operation flags.
---

The `api:` section controls global API settings, URL prefixes, and default operation flags.

## Schema

```yaml
api:
  basePath: /api          # optional, default: ""
  version: v1             # optional, default: ""
  port: 8000              # optional, default: 8000
  cors:                   # optional
    origins: ["*"]
    methods: ["*"]
    headers: ["*"]
    credentials: false
  operations:
    defaults:
      list: true
      get: true
      create: true
      update: true
      replace: false
      delete: true
    auth:
      register: true
      login: true
```

## Fields

### `basePath`

Type: string. Default: `""`.

Prepended to all route paths. Example: `basePath: /api` + `base_path: /posts` = `/api/posts`.

### `version`

Type: string. Default: `""`.

API version segment inserted after `basePath`. Example: `basePath: /api`, `version: v1` → `/api/v1/posts`.

### `port`

Type: integer. Default: `8000`.

The default port the generated application will listen on. This value can be overridden at runtime using the `PORT` environment variable.

### `cors`

Type: object. Optional.

Configures Cross-Origin Resource Sharing (CORS) for the API.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `origins` | list of strings | `["*"]` | Allowed origins. |
| `methods` | list of strings | `["*"]` | Allowed HTTP methods. |
| `headers` | list of strings | `["*"]` | Allowed HTTP headers. |
| `credentials` | boolean | `false` | Whether to allow credentials (cookies, authorization headers, or TLS client certificates). |

### `operations.defaults`

Controls which CRUD operations are enabled globally. Individual repositories and controllers can override these.

| Field | Type | Default |
|-------|------|---------|
| `list` | boolean | `true` |
| `get` | boolean | `true` |
| `create` | boolean | `true` |
| `update` | boolean | `true` |
| `replace` | boolean | `false` |
| `delete` | boolean | `true` |

`replace` is `false` by default because PUT semantics (full document replacement) are a separate opt-in.

### `operations.auth`

Controls which auth operations are auto-generated for auth entities.

| Field | Type | Default |
|-------|------|---------|
| `register` | boolean | `true` |
| `login` | boolean | `true` |

## Minified list syntax

`defaults` also accepts a list of operation names as shorthand:

```yaml
api:
  operations:
    defaults: [list, get, create, update, delete]
```

This enables exactly the listed operations and disables all others.

## Example

```yaml
api:
  basePath: /api
  version: v1
  port: 8080
  cors:
    origins: ["http://localhost:3000"]
  operations:
    defaults:
      list: true
      get: true
      create: true
      update: true
      replace: false
      delete: true
    auth:
      register: true
      login: true
```
