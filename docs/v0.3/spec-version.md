---
title: Spec version 0.3
description: Opt in to the v0.3 spec, what it adds to v0.2, and the operators a where binding accepts.
---

## Opting in

Select the spec version at the top of your file:

```yaml
version: "0.3"
```

A `version: "0.3"` spec runs the same validation and desugaring pipeline as
v0.2. An unknown version (for example `"9.9"`) is rejected with the
`UNSUPPORTED_VERSION` error.

## Differences from v0.2

A v0.2 spec is a valid v0.3 spec once its `imports` entries use the object form
described below. The v0.3 schema lives at
`parsers/schemas/yaml-spec-v0.3.schema.json` and extends v0.2 with:

- **[`where` binding form](./given-where.md)** &mdash; access-rule `given:`
  values may bind a record by predicate over fields, `$`-sigil symbols, and
  literals (for example `orders where ownerId = $userId and orgId = $orgId`).
- **[service `input:` / `with:`](./service-input.md)** &mdash; a service declares,
  validates, and forwards request values to a repository operation or handler.
- **[access-rule `bind:`](./controller-bind.md)** &mdash; the matched
  authorization rule supplies trusted values for a service's declared inputs.
- **[vendored `imports:`](./vendored-imports.md)** &mdash; each `imports` entry is
  an object that copies a custom-handler package into the generated target and
  merges its dependencies into the manifest.
- **[pagination](./pagination.md)** &mdash; `pagination:` on a list route or
  operation override.
- **[file fields](./file-fields.md), [file datastores](./file-datastores.md) and
  [file endpoints](./file-endpoints.md)** &mdash; `type: file` fields, `api.files`,
  `repositories.<name>.files` and the `filesystem`/`s3` datastores.
- **[PKCE](./pkce.md) and [DPoP](./dpop.md)** &mdash; `pkce` and `dpop` on an OIDC
  provider.
- **`$`-sigil slugs** &mdash; symbolic references such as `$userId`, resolved at
  build or call time.

## `where` operators

A `where` binding compares fields with `=` and joins comparisons with `and`.
The operators `!=`, `<`, `<=`, `>`, `>=` and `in` are rejected with
`WHERE_OPERATOR_UNSUPPORTED`.
