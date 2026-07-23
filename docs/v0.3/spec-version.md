---
title: Spec version 0.3
description: Opt in to the v0.3 spec, a superset of v0.2, and the reserved-vs-active where operators.
---

## Opting in

Select the spec version at the top of your file:

```yaml
version: "0.3"
```

A `version: "0.3"` spec runs the same shared validation and desugaring pipeline as
v0.2 and is transformed by `V03Transformer`, which subclasses the v0.2 transformer.
A `version: "0.2"` spec is unaffected and behaves exactly as before. An unknown
version (for example `"9.9"`) is rejected with the `UNSUPPORTED_VERSION` error.

## A superset of v0.2

Every spec that is valid under v0.2 is valid under v0.3. Opting in changes nothing
about existing constructs; it only unlocks the additional v0.3 constructs below.
The v0.3 schema lives at `parsers/schemas/yaml-spec-v0.3.schema.json` and is a copy
of the v0.2 schema extended permissively with:

- **`where` binding form** &mdash; access-rule `given:` values may be `where`
  expressions over fields, `$`-sigil symbols, and literals (for example
  `ownerId = $userId and orgId = $orgId`).
- **service `input:` / `with:`** &mdash; a service declares the named inputs it
  requires (`input:`) and forwards values into a called service (`with:`).
- **controller / access-rule `bind:`** &mdash; supplies values for a service's
  declared inputs.
- **`$`-sigil slugs** &mdash; symbolic references such as `$userId`, resolved at
  build or call time.

These constructs are accepted **syntactically** in v0.3; their runtime semantics
are delivered by later v0.3 issues.

## `where` operators: active vs reserved

The `where` operator set is reserved in the schema so that specs written against
future v0.3 releases validate today. Only a subset is active:

| Operator | Status |
| --- | --- |
| `=` | Active |
| `and` | Active |
| `!=` | Reserved (not yet implemented) |
| `<` | Reserved (not yet implemented) |
| `<=` | Reserved (not yet implemented) |
| `>` | Reserved (not yet implemented) |
| `>=` | Reserved (not yet implemented) |
| `in` | Reserved (not yet implemented) |

Reserved operators are recognized by the schema but carry no runtime behavior yet.
Use only `=` and `and` in expressions you expect to run.
