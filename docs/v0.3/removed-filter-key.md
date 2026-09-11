---
title: The removed access-rule `filter` key
description: The dead `filter` key is gone from the v0.3 access rule; using it aborts with a coded error.
---

## The `filter` key is removed

The access-rule `filter` key was carried in the IR but never enforced by the
runtime or generated backends. Leaving it available could make an apparently
restricted rule authorize more records than intended. In v0.3 it is removed
from the grammar, and a rule that still declares it aborts generation with
`ACCESS_FILTER_REMOVED`:

```yaml
access:
  - given:
      principal: identity:user
    filter: "ownerId = principal.sub"   # ACCESS_FILTER_REMOVED
```

## Scope reads through `where` instead

Restricting which records a principal may reach is the job of the `where`
[binding form](./given-where.md): bind a `given:` symbol to the one record the
predicate selects before the rule runs. A lookup miss makes that rule fail; if
no other rule allows the request, authorization returns 403 without revealing
whether the record exists.

```yaml
access:
  - given:
      principal: identity:user
      owned: posts where ownerId = $principal.sub
```

## v0.2 is unchanged

Under `version: "0.2"` the `filter` key is still parsed and preserved on the
rule exactly as before; the removal applies only to `version: "0.3"`.
