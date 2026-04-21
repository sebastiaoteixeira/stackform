---
title: "Reference: Controller Operations"
description: Each key under `controllers.<name>.operations` configures one HTTP route.
---

Each key under `controllers.<name>.operations` configures one HTTP route.

## Operation config fields

```yaml
operations:
  operationName:
    method: POST          # HTTP method
    path: "/{id}/action"  # path relative to base_path
    access: <accessValue> # access rule for this operation
```

All three fields are optional. Omitted fields use the defaults for the operation name.

## Default method and path per operation name

| Operation | Default method | Default path |
|-----------|---------------|--------------|
| `list` | GET | `/` |
| `get` | GET | `/{id}` |
| `create` | POST | `/` |
| `update` | PATCH | `/{id}` |
| `replace` | PUT | `/{id}` |
| `delete` | DELETE | `/{id}` |
| `register` | POST | `/register` |
| `login` | POST | `/login` |
| custom | inferred | inferred from name |

`{id}` is replaced with the entity's primary key field name (e.g., `{code}` for an entity with `pk: code`).

## Custom operation path/method

Custom operations must explicitly set `method:` and `path:` if the default inference is not suitable:

```yaml
operations:
  publish:
    method: POST
    path: "/{id}/publish"
    access: "*"
```

## Access shorthand

Single-value access can use inline form:

```yaml
operations:
  create: { access: "*" }
  list: { access: public }
  update: { access: moderator }
```

## Access with ABAC list

```yaml
operations:
  delete:
    access:
      - admin
      - given:
          principal: identity:user
          document: posts
        when: principal.sub equals document.authorId
```

## Disabling an operation

To disable an operation at the controller level (even if the underlying service/repository supports it), omit it from `operations:`. Routes are only generated for operations that are explicitly configured or inherited from defaults.

If you want to block a globally-enabled operation for a specific controller, set its access to a restricted rule that no principal can satisfy, or simply do not wire the operation through the service.
