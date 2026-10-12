---
title: Service `input:` and `with:` forwarding
description: Declare the request values a service requires and map them to its repository operation or custom handler.
---

# Service `input:` and `with:` forwarding

In v0.3, a service declares the request values it requires with `input:` and
maps those validated values to its repository operation or custom handler with
`with:`. Both the in-process server and generated FastAPI, DRF, and raw-ASGI
backends enforce the same contract. A v0.2 spec using either key is rejected
with `SERVICE_INPUT_UNSUPPORTED`.

## Declaring inputs

`input:` is an inline field map or a non-empty list of DTO names. DTO fields are
merged into one input contract.

```yaml
services:
  archivePost:
    repository: posts
    operation: archive
    input:
      postId: string
      reason:
        type: string
        required: false
  publishPost:
    handler: app.handlers.publish
    input: [PublishRequest]
```

The supported field types are `string`, `number`, `boolean`, `datetime`,
`enum`, `array`, `object`, and `ref`. The normal `min`, `max`, `minLength`,
`maxLength`, and `values` constraints apply. Fields are required unless their
configuration sets `required: false`.

Values come from JSON body fields and route path parameters. A path parameter
wins when the body contains the same name, so a body cannot spoof a route
identity. Missing or invalid inputs return 422 before the repository operation
or handler runs. An optional input may be absent or `null`.

## Forwarding values

`with:` maps a downstream name to a declared `$input` or to a YAML scalar
literal. Strings are ordinary YAML strings; no nested quoting is required.

```yaml
services:
  archivePost:
    repository: posts
    operation: archive
    input:
      postId: string
    with:
      lookup: $postId
      state: archived
      audit: true
      retries: 3
```

Dotted references such as `$payload.owner.id` traverse object inputs. A symbol
may reference only a field declared by the same service's `input:`. An unbound
name aborts the build with `UNDEFINED_SYMBOL`.

For a repository-backed service, each `with:` key is a root symbol available to
the operation query. Every query symbol must be supplied on every route that
reaches the operation, either by a route slug or by `with:`.

```yaml
repositories:
  posts:
    operations:
      archive:
        query:
          command: findOne
          filter:
            id: $lookup
            state: $state
```

A forwarding key that the repository query does not reference is rejected with
`SERVICE_WITH_TARGET_UNKNOWN`. This catches misspelled targets rather than
silently discarding a value.

For custom handlers, resolved values are exposed without changing the handler
signature:

- `stackform run`: `context.service_inputs`
- generated FastAPI and raw-ASGI: `request.state.service_inputs`
- generated DRF: `request.service_inputs`

## Error codes

| Code | Raised when |
| --- | --- |
| `SERVICE_INPUT_UNSUPPORTED` | `input:` or `with:` is used before v0.3 |
| `SERVICE_INPUT_INVALID` | `input:` is neither a non-empty field map nor a non-empty DTO list |
| `SERVICE_INPUT_FIELD_INVALID` | an input field type or `required` flag is invalid |
| `SERVICE_INPUT_DTO_NOT_FOUND` | an input lists a DTO that does not exist |
| `SERVICE_WITH_VALUE_INVALID` | a forwarded value is not a `$symbol` or scalar literal |
| `SERVICE_WITH_TARGET_UNKNOWN` | a repository forwarding key is unused by its operation query |
| `UNDEFINED_SYMBOL` | a `with:` symbol is not declared by the service input |
