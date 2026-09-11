# Access-rule `bind:`

In v0.3, an access rule can supply trusted service inputs after it authorizes a
request. The in-process server and generated FastAPI, DRF, and raw-ASGI
backends enforce the same behavior. A v0.2 rule cannot use `bind:`.

Rules remain ordered. The first matching rule decides the request: a matching
deny rule returns 403, while a matching allow rule supplies only its own
`bind:` values. Bindings on non-matching, denied, or later rules never run.

## Supplying trusted inputs

Each key must name a field declared by the route's service `input:`. Values use
the same syntax as service `with:`: a `$symbol` reference or a YAML scalar
literal.

```yaml
services:
  archivePost:
    repository: posts
    operation: archive
    input:
      postId: string
      owner: string
    with:
      lookup: $postId
      actor: $owner

controllers:
  posts:
    base_path: /posts
    routes:
      archive:
        service: archivePost
        method: POST
        path: "/{postId}/archive"
        access:
          - given:
              principal: identity:user
            bind:
              owner: $principal.sub
```

Here the path supplies `postId` and the matched rule supplies `owner`. Bind
values are trusted and take precedence over body and path values with the same
name, so a caller cannot replace `owner` in the JSON body. The combined inputs
are type-checked against `input:` and then mapped through `with:`. Repository
operations and custom handlers receive the mapped `with:` values in the same
way described in [Service `input:` and `with:` forwarding](service-input.md).

A rule with `bind:` must statically cover every required service input through
either a bind key or a route path parameter. Optional inputs may be omitted.
Every bind key must be declared by the service input contract.

## Symbol scope

A bind expression can reference:

- route path parameters;
- identity symbols declared in the same rule's `given:` mapping, such as
  `$principal.sub` or `$principal.record.orgId`;
- request symbols declared in the same rule, including body, path, query,
  header, and cookie bindings;
- YAML scalar literals: strings, numbers, and booleans.

There are no ambient identity or request roots. For example, `$principal` is
valid only when that rule declares `principal: identity:<entity>`.

Document bindings cannot be combined with route-level bind. Service inputs must
be finalized before the service runs, while document bindings belong to the
record-authorization lifecycle. Keep a bind-producing route limited to path,
identity, and request symbols.

## Failures

Invalid specs fail at build time:

| Code | Raised when |
| --- | --- |
| `BIND_UNSUPPORTED` | an access rule uses `bind:` before v0.3 |
| `UNDEFINED_SYMBOL` | a referenced root is not a route parameter or an identity/request symbol declared by the same rule |
| `BIND_TARGET_UNKNOWN` | a bind key is absent from the service `input:` contract |
| `BIND_MISSING_REQUIRED_INPUT` | a required service input is supplied by neither the rule nor a route path parameter |
| `BIND_DOCUMENT_RULE_UNSUPPORTED` | a route combines bind with any document-binding rule |
| `SERVICE_WITH_VALUE_INVALID` | a bind value is neither a symbol reference nor a YAML scalar literal |

At runtime, a missing or ill-typed resolved value returns 422 during normal
service-input validation. Authorization failures return 401 or 403 before any
binding is applied.
