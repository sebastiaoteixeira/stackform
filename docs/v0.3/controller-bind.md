# Access-rule `bind:`

An access rule authorizes a request; `bind:` lets that same rule *supply the
operation's service inputs* once it authorizes. It is v0.3-only -- a v0.2 spec
never carries it and behaves byte-identically.

Access rules are evaluated top-down as an **OR**: the first rule that matches
authorizes the request, gates it, and its `bind:` resolves the inputs. A later
rule's `bind:` never runs once an earlier rule has matched.

## Binding inputs from a rule's own scope

`bind:` maps a service input name to a value drawn from the matched rule's own
scope. Each right-hand side is a `$symbol` or a literal, exactly as in service
`with:`:

```yaml
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
              owner: $principal.id   # from this rule's given: principal
              id: $postId            # from the ambient route slug
              state: 'archived'      # a literal
```

The resolved values are merged into the request's parameters and exposed on the
context as `ctx.service_inputs`, so the operation's service `input:` validation
and its repository/handler see them.

## Symbol scope

A `bind:` right-hand-side `$symbol` resolves against the **route slugs** (which
are ambient) plus the **symbols the same rule binds in its own `given:`**.

- **Route slugs are ambient.** A rule that gates on a role alone -- no `given:`
  -- can still `bind:` from the path slugs.
- **`$principal` is not ambient.** It resolves only when the same rule declares
  it, e.g. `given: { principal: identity:user }`. Without that `given:`, a
  `$principal` reference is unbound.
- **Request parts still need a `given:`.** To bind from the body, query, header,
  or cookie, name it as a `given:` symbol first, then reference that symbol.

Any `$symbol` outside this scope aborts generation with the uniform
`UNDEFINED_SYMBOL` error, naming the symbol and the scope
(`controller '<c>' route '<r>' access[<i>] bind`). A `bind:` made entirely of
literals and slugs needs no `given:`.

## Error codes

| Code | Raised when |
| --- | --- |
| `UNDEFINED_SYMBOL` | a `bind:` `$symbol` is neither a route slug nor a symbol the same rule binds in `given:` |
