---
title: Explainable access denials
description: Return a safe, rule-specific reason when an explicit v0.3 deny rule matches.
---

## Rule-specific denial details

The optional `reason:` key is a client-visible explanation for an explicit
`then: deny` rule. In a v0.3 spec, when that rule is the first matching access
rule, its reason becomes the `detail` field of the `403 Forbidden` response.

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

## Generic denials

The response remains `{ "detail": "Forbidden" }` when:

- the matching deny rule has no reason or has an empty reason;
- no rule matches and authorization falls through; or
- the spec version is v0.1 or v0.2, where `reason:` remains inert metadata.

Reasons on allow rules and non-matching deny rules are never returned. Rules
are evaluated in order, so only the first matching rule can determine the
response.

## Security guidance

A reason is part of the public API response. Do not put secrets, internal policy
expressions, tenant or record existence details, stack traces, or operator-only
diagnostics in it. Prefer a stable message that tells the caller what action is
not permitted without revealing why a sensitive predicate matched.
