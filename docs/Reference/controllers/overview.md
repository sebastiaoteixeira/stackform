# Reference: Controllers Overview

Controllers define HTTP route configuration. They bind services to HTTP methods and paths, and declare access rules.

## Structure

```yaml
controllers:
  controllerName:
    service: serviceName
    base_path: /path
    access: <accessValue>          # default for all operations
    operations:
      operationName:
        method: GET | POST | PATCH | PUT | DELETE
        path: /subpath
        access: <accessValue>      # overrides controller-level access
```

## Fields

### `service`

Type: string (service name). Required.

The service this controller routes to. Must match a key in `services:`.

### `base_path`

Type: string. Required.

URL prefix for all routes in this controller. Combined with `api.basePath` and `api.version`.

### `access`

Type: access value (see [access-control](./access-control.md)). Optional. Default: no default (must be set per-operation if omitted).

Default access rule applied to all operations. Individual operations can override this.

### `operations`

Type: map. Optional.

Per-operation configuration. Keys are operation names (`list`, `get`, `create`, `update`, `replace`, `delete`, `register`, `login`, or custom names).

Each operation can specify:
- `method:` — HTTP method override
- `path:` — path override (relative to `base_path`)
- `access:` — access rule override

## Default routes for standard operations

When `method:` and `path:` are not specified, the engine uses these defaults:

| Operation | Method | Path |
|-----------|--------|------|
| `list` | GET | `/` |
| `get` | GET | `/{id}` |
| `create` | POST | `/` |
| `update` | PATCH | `/{id}` |
| `replace` | PUT | `/{id}` |
| `delete` | DELETE | `/{id}` |
| `register` | POST | `/register` |
| `login` | POST | `/login` |

`{id}` is the primary key parameter name (matches the `type: id` field name or `pk:` field name).

## Example

```yaml
controllers:
  users:
    service: users
    base_path: /users
    access: "*"
    operations:
      register: { access: public }
      login: { access: public }
      delete:
        access:
          - given:
              principal: identity:user
              document: users
            when: principal.sub equals document.id

  posts:
    service: posts
    base_path: /posts
    access: public
    operations:
      create: { access: "*" }
      publish:
        method: POST
        path: "/{id}/publish"
        access: "*"
```
