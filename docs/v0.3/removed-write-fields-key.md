---
title: The removed access-rule `writeFields` key
description: v0.3 rejects the formerly inert writeFields key instead of presenting an unenforced authorization boundary.
---

## `writeFields` is not an authorization control

The legacy access-rule `writeFields` key was parsed into the intermediate model
but never enforced by the runtime server or generated backends. A spec could
therefore appear to limit which fields a principal may write while accepting the
entire request payload.

Under `version: "0.3"`, using the key aborts generation with
`ACCESS_WRITE_FIELDS_REMOVED`:

```yaml
access:
  - given:
      principal: identity:user
    writeFields: [title, content] # ACCESS_WRITE_FIELDS_REMOVED
```

Rejecting the declaration is fail-safe: a security-looking rule cannot silently
grant broader write access than its author intended.

## Restricting write input

Use a v0.3 service [`input:` contract](service-input.md) to declare and validate
the values an operation accepts. Use access-rule [`bind:`](controller-bind.md)
for trusted values derived from the authorized principal or request. When the
allowed field set itself depends on a role or policy, enforce that policy in a
custom handler rather than declaring `writeFields`.

## v0.2 compatibility

v0.2 continues to parse and preserve `writeFields` for compatibility, but it
does not enforce it. Do not rely on the key as an authorization boundary in a
v0.2 application.
