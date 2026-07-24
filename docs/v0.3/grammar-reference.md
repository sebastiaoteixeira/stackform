---
title: Access and binding grammar reference
description: Consolidated v0.3 reference for where, given forms, bind, service input/with, $-sigil symbols and scopes, active vs reserved where operators, and coded errors.
---

# Access and binding grammar reference

A single reference for the v0.3 access-and-binding constructs. Each is a superset
addition over v0.2: a `version: "0.2"` spec never sees any of them, and opting in
with `version: "0.3"` unlocks them without changing any existing behavior. The
authoritative grammar is `parsers/schemas/yaml-spec-v0.3.schema.json`.

Constructs are accepted **syntactically** in v0.3. Where a construct's runtime
semantics are delivered by a later v0.3 issue, that is called out inline; the
schema is the contract that lets forward-written specs validate today.

## Opting in

```yaml
version: "0.3"
```

An unknown version (for example `"9.9"`) is rejected with `UNSUPPORTED_VERSION`.
See [Spec version 0.3](spec-version.md) for the version gate.

## `$`-sigil symbols and scopes

A symbol is a `$`-prefixed slug that names a value resolved at build or call time
rather than a literal.

```
Symbol  ::=  "$" ( letter | "_" ) ( letter | digit | "_" )*
```

Examples: `$userId`, `$orgId`, `$user_id`. A symbol carries no value on its own;
it is *bound* by the surrounding construct (`bind:`, `with:`) or by the request
scope in which the enclosing rule runs. A symbol referenced but not bound in its
scope is an unresolved reference; the diagnostic for that is delivered with the
symbol-resolution semantics in a later v0.3 issue.

## `where` binding form

An access rule's `given:` value may be a `where` expression: a boolean predicate
over fields, `$`-sigil symbols, and literals, joined by `and`.

```yaml
access:
  - given: ownerId = $userId and orgId = $orgId
    effect: allow
```

```
WhereExpression  ::=  Conjunct ( "and" Conjunct )*
Conjunct         ::=  Field Operator Rhs
Rhs              ::=  Symbol | Literal
```

The schema accepts a `WhereExpression` as any string matching
`^[\w$][\w$.'"\s=<>!,()-]*$`, so forward-written specs using reserved operators
validate. Runtime evaluation is restricted to the active operator set below.

### `where` operators: active vs reserved

| Operator | Status |
| --- | --- |
| `=` | Active |
| `and` | Active |
| `!=` | Reserved |
| `<` | Reserved |
| `<=` | Reserved |
| `>` | Reserved |
| `>=` | Reserved |
| `in` | Reserved |

Reserved operators are recognized by the schema but carry no runtime behavior
yet. Use only `=` and `and` in expressions you expect to run.

## `given` forms

The `given:` map assigns a principal requirement to each named subject. A value
takes one of these forms:

| Form | Example | Meaning |
| --- | --- | --- |
| `public` | `user: public` | No authentication required. |
| `authenticated` | `user: authenticated` | Any authenticated principal. |
| `identity:<collection>` | `user: identity:users` | A principal from the named identity collection. |
| `where` expression | `given: ownerId = $userId` | Record-scoped predicate (see above). |

The identity form matches `^identity:[A-Za-z_][A-Za-z0-9_]*$`. An access rule
must carry at least one of `given:`, `when:`, or `then:`.

## `bind:`

`bind:` supplies values for a called service's declared inputs from a controller
route or an access rule. It is a `SymbolBinding`: a non-empty map of input names
to `$`-sigil symbols or request/identity references.

```yaml
controllers:
  orders:
    routes:
      create:
        service: orders
        method: POST
        path: /orders
        bind:
          userId: $userId
```

```
SymbolBinding  ::=  { name: (Symbol | Reference) , ... }   # at least one entry
```

Forwarding semantics land in a later v0.3 issue.

## Service `input:` and `with:`

A service declares the named inputs it requires with `input:`, and forwards values
into a called service with `with:` (also a `SymbolBinding`).

```yaml
services:
  orders:
    input: [userId, orgId]
    with:
      userId: $userId
```

`input:` is either a non-empty list of names or a non-empty map. `with:` is a
`SymbolBinding`, structurally identical to `bind:`. A `bind:`/`with:` entry
supplies exactly one declared `input:`; wiring and validation semantics land in a
later v0.3 issue.

## Related v0.3 runtime behavior

These features are runtime, not grammar, but complete the access story:

- [Access rule `reason`](access-reason.md) &mdash; the `reason:` string is
  surfaced in the `403 Forbidden` body when its rule denies a request.
- [Unique violation `409 Conflict`](conflict-status.md) &mdash; a duplicate on a
  `unique` field answers `409` naming the offending field.

## Coded errors

| Code | When | Status |
| --- | --- | --- |
| `UNSUPPORTED_VERSION` | `version:` names a spec with no built-in schema. | Active |
| `DESUGAR_SERVICE_NOT_FOUND` | A route or controller references an undefined service. | Active |
| `DESUGAR_ABSTRACT_SERVICE_BOUND` | An abstract service is bound directly to a route. | Active |

Diagnostics for `where` evaluation, `bind:`/`with:` wiring, and symbol resolution
are introduced alongside those constructs' runtime semantics in later v0.3 issues;
until then the constructs above are validated for shape only.
