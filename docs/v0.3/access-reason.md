# Access rule `reason`

The optional `reason:` key on an access rule is a human-readable explanation of
why the rule denies a request. In v0.2 it parsed and validated but had no runtime
effect. From v0.3 the string is surfaced in the `403 Forbidden` response body when
that rule denies the request.

```yaml
access:
  - principal: identity:users
    effect: deny
    when: { $doc.status: locked }
    reason: This record is locked and cannot be modified.
```

A request denied by the rule above receives:

```json
{ "detail": "This record is locked and cannot be modified." }
```

Behavior is unchanged for rules without a `reason:`: the body stays
`{"detail": "Forbidden"}`. The generic detail is also used when a request is
denied by falling through all rules with no explicit matching deny, since no
single rule owns that outcome.

The reason is surfaced identically on both the request-time authorization step
and the post-fetch (document-scoped) authorization step.
