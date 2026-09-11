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

## Compatibility with v0.2

Most v0.2 specs remain valid under v0.3. The exception is the dead access-rule
`filter` key: it was never enforced and is rejected in v0.3 to prevent a false
sense of authorization. The v0.3 schema lives at
`parsers/schemas/yaml-spec-v0.3.schema.json` and derives from v0.2 with these
changes:

- **[`where` binding form](./given-where.md)** &mdash; access-rule `given:`
  values may bind a record by predicate over fields, `$`-sigil symbols, and
  literals (for example `orders where ownerId = $userId and orgId = $orgId`).
- **[service `input:` / `with:`](./service-input.md)** &mdash; a service declares,
  validates, and forwards request values to a repository operation or handler.
- **[controller / access-rule `bind:`](./controller-bind.md)** &mdash; the matched
  authorization rule supplies trusted values for a service's declared inputs.
- **`$`-sigil slugs** &mdash; symbolic references such as `$userId`, resolved at
  build or call time.
- **[removed access-rule `filter`](./removed-filter-key.md)** &mdash; v0.3 rejects
  this unenforced legacy key with `ACCESS_FILTER_REMOVED`.

Service `input:` / `with:` and controller `bind:` are implemented in the runtime
server and generated backends. A construct is not listed as implemented until
its parser, runtime behavior, generated output, tests, and reference docs are
present.

## `where` operators: active vs reserved

The `where` operator set is reserved so that specs written against future v0.3
releases stay within the schema's character set today. Only a subset is active:

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

Reserved operators pass the schema but are rejected by the where parser with
`WHERE_OPERATOR_UNSUPPORTED`, so a spec using one does not build. Use only `=`
and `and`.
