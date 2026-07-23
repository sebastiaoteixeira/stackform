---
title: Symbol resolution
description: The v0.3 scope/binding model and the single undefined-symbol error.
---

## Every symbol resolves against its scope

In v0.3 every `$<symbol>` reference resolves against the names **bound in its
current scope**. A symbol is defined only if something bound it:

- an access rule's `given:` binding,
- a service `input:` declaration,
- a slug declared in a route template (for example `{orderId}` in `/orders/{orderId}`),
- and, in later releases, a service `with:` forward or a controller / access-rule `bind:`.

There are **no built-in or ambient roots** except route-declared slugs. A
reference that nothing bound in its scope aborts generation.

## The single coded error

A symbol that is not bound in its scope produces one coded error,
`UNDEFINED_SYMBOL`, naming the symbol and the scope:

```
symbol $principal is not bound in scope repository 'orders' operation 'byOwner' filter
```

The same rule and the same error apply at every site where symbols resolve: a
`when:` operand, a repository query filter, and &mdash; as later v0.3 issues add
them &mdash; a `where` right-hand side, a service `with:` forward, and a
controller / access-rule `bind:`. Each site builds a scope carrying its bound
names and a label, then defers to the shared resolver, so the rule is enforced
identically everywhere.

## `$principal` is not ambient in v0.3

Because nothing binds `$principal` in a repository scope, a repository filter
that references it aborts. This is a direct consequence of the general rule, not
a special case:

```yaml
repositories:
  orders:
    entity: order
    operations:
      byOwner:
        query:
          command: find
          filter: { ownerId: "$principal" }   # UNDEFINED_SYMBOL
```

A route slug, by contrast, is bound in the scope of the operations its route
reaches, so it resolves normally:

```yaml
repositories:
  orders:
    entity: order
    operations:
      byId:
        query:
          command: find
          filter: { _id: "$orderId" }          # resolves: {orderId} is a route slug
controllers:
  orders:
    base_path: /orders
    routes:
      byId: { service: byId, method: GET, path: "/{orderId}", access: public }
```

Service-supplied free symbols (for example `$organizationId` bound through a
service `input:` / `with:`) resolve the same way once those constructs are
active.

## v0.2 is unchanged

This model applies only to `version: "0.3"`. A `version: "0.2"` spec keeps its
existing behavior: `when:` operands report the legacy `WHEN_UNBOUND_SYMBOL`
error, and repository filters keep their ambient `principal` / request roots.
