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
- a service `with:` forwarding key.

There are **no built-in or ambient roots** except route-declared slugs. A
reference that nothing bound in its scope aborts generation.

## The single coded error

A symbol that is not bound in its scope produces one coded error,
`UNDEFINED_SYMBOL`, naming the symbol and the scope:

```
symbol $principal is not bound in scope repository 'orders' operation 'byOwner' filter
```

The same rule and error apply to a `when:` operand, repository query filter,
[`where` right-hand side](./given-where.md#symbol-scope), and service `with:`
forward. Each site builds an explicit scope and delegates to the shared
resolver.

A `where` binding's scope is the route's slugs plus the `identity:` / `request`
names its rule binds; document bindings of the same rule are not in scope. Its
left-hand-side field is checked separately and reports `WHERE_FIELD_UNKNOWN`,
not `UNDEFINED_SYMBOL`.

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

Service forwarding keys are also bound roots. A repository query may reference
`$organizationId` when the route's service supplies an `organizationId` key in
`with:`. Validation is per route, so one correctly bound route cannot hide a
missing binding on another route to the same operation.

## v0.2 is unchanged

This model applies only to `version: "0.3"`. A `version: "0.2"` spec keeps its
existing behavior: `when:` operands report the legacy `WHEN_UNBOUND_SYMBOL`
error, and repository filters keep their ambient `principal` / request roots.
