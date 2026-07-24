---
title: The removed access-rule `filter` key
description: The dead `filter` key is gone from the v0.3 access rule; using it aborts with a coded error.
---

## The `filter` key is removed

The access-rule `filter` key never scoped anything at runtime &mdash; it was
carried in the IR but no generator ever consumed it. In v0.3 it is removed from
the grammar. A rule that still declares it aborts generation with
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
predicate selects, fetched before the rule runs, with a `404` on miss.

```yaml
access:
  - given:
      principal: identity:user
      owned: posts where ownerId = $principal.sub
```

## v0.2 is unchanged

Under `version: "0.2"` the `filter` key is still parsed and preserved on the
rule exactly as before; the removal applies only to `version: "0.3"`.
