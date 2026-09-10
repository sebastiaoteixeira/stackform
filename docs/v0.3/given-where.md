---
title: The `where` binding form
description: Bind a `given:` symbol to one record fetched by predicate, with 404-on-miss.
---

## Binding a record by predicate

In v0.3 an access rule's `given:` gains the `where` binding form: it binds a
symbol to a single record fetched from a collection by an equality predicate
rather than by the implicit `{id}` / primary-key lookup.

```yaml
controllers:
  assets:
    base_path: /categories
    routes:
      listAssets:
        service: listAssets
        method: GET
        path: /{categorySlug}/assets
        access:
          - given:
              principal: identity:user
              category: assetCategories where slug = $categorySlug
            when: category.owner = principal.sub
```

Here `category` is bound to the one `assetCategories` record whose `slug` equals
the route slug `$categorySlug`. The bound record is then available to the rule's
`when:` (and to any other rule construct that resolves symbols).

## Grammar

```
<collection> where <field> = <rhs> [and <field> = <rhs>]*
```

- Only the `=` operator and the `and` conjunction are **active**.
- The operators reserved by the v0.3 schema &mdash; `!=`, `<`, `<=`, `>`, `>=`,
  `in` &mdash; are accepted syntactically but **not implemented**; using one
  aborts generation with `WHERE_OPERATOR_UNSUPPORTED`.

### Right-hand sides

Each `<rhs>` is one of:

- an **ambient route slug** &mdash; `$categorySlug` where `{categorySlug}` is a
  token in the route path;
- a **symbol bound by this rule's `given:`** &mdash; for example
  `$principal.record.id` when `principal` is bound in the same `given:`;
- a **literal** &mdash; a single-quoted string (`'open'`), a number (`3`,
  `1.5`), or `true` / `false`.

Every `$`-sigil right-hand side resolves through the shared v0.3
[symbol resolution](./symbol-resolution.md) model. Its scope's bound names are
the route-declared slugs plus the symbols this rule binds in `given:`; an
unbound reference aborts with the single `UNDEFINED_SYMBOL` error, for example:

```
symbol $ghost is not bound in scope controller 'assets' route 'listAssets' access[0] given 'category' where
```

## Replaces the implicit fetch; 404 on miss

Under v0.3 the `where` form **replaces the implicit `{id}` / primary-key fetch**
for that document binding. The record is fetched by the predicate before the
rule is evaluated, and a predicate that matches **no record yields `404`** (the
same `NotFoundError` the framework raises for a missing resource) &mdash; a
record outside the bound set is not found. A record that is found but fails the
rule's condition is a `403`, as with any other document binding.

## v0.2 is unchanged

The `where` binding form is available only under `version: "0.3"`. A
`version: "0.2"` document binding (`<collection>` or `<collection> by <param>`)
keeps its implicit primary-key / `{id}` fetch and byte-identical behavior; the
string ` where ` carries no special meaning in v0.2.
