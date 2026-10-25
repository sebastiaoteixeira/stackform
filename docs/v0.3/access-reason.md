---
title: Explainable access denials
description: Return a safe, rule-specific reason in a 403 response.
---

## Rule-specific denial details

The optional `reason:` key is a client-visible explanation of a `403 Forbidden`
response. When an explicit `then: deny` rule is the first matching access rule,
its reason becomes the `detail` of the response.

```yaml
access:
  - given:
      principal: identity:user
      document: posts
    when: principal.sub not equals document.ownerId
    then: deny
    reason: Only the owner may modify this post.
  - then: allow
```

The matched deny above returns:

```json
{ "detail": "Only the owner may modify this post." }
```

The behavior is the same in `stackform run` and in generated FastAPI, Django
REST Framework, and raw ASGI backends. It applies to rules evaluated before a
record fetch and to document-scoped rules evaluated after the record is loaded.

## Denials no rule decides

When no rule matches a signed-in caller, the `detail` is the reason of the
first allow rule that carries one, so an allow rule can say what it requires:

```yaml
access:
  - given:
      principal: identity:user
    when: principal.record.role in ['editor', 'admin']
    reason: Only editors may publish.
```

A viewer is answered `{ "detail": "Only editors may publish." }`. The detail is
`Forbidden` when the matching deny rule has no reason, or when no rule matches
and no allow rule has one. An anonymous caller that no rule admits gets `401`,
which carries no reason. A deny rule that does not match never supplies the
detail.

## Security guidance

A reason is part of the public API response. Do not put secrets, internal policy
expressions, tenant or record existence details, stack traces, or operator-only
diagnostics in it. Prefer a stable message that tells the caller what action is
not permitted without revealing why a sensitive predicate matched.
