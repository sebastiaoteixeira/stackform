---
title: The `where` binding form
description: Bind a `given:` symbol to one record fetched by an equality predicate; a predicate that matches nothing makes the rule fail.
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
            when: category.owner equals principal.sub
```

Here `category` is bound to the one `assetCategories` record whose `slug` equals
the route slug `$categorySlug`. The bound record is then available to the rule's
`when:` like any other document binding.

The form is recognized in the `given:` of a route `access:` rule under
`version: "0.3"`. A `given:` value inside a `policies:` definition is still read
as a plain `<collection>[ by <param>]` document binding.

## Grammar

```
<collection> where <field> = <rhs> [and <field> = <rhs>]*
```

The where parser (`parsers/where_parser.py`) is the authority on the grammar; the
v0.3 schema's `WhereExpression` pattern only bounds the character set. A `given:`
value is treated as a `where` binding when it contains the bare keyword `where`
outside quotes, so `assetCategories where slug=$categorySlug` parses and
`posts by 'where'` stays a v0.2 document binding.

- `<collection>` and `<field>` are plain identifiers. `<field>` is a top-level
  field of the collection's entity; a dotted path (`owner.id`) is rejected with
  `WHERE_BINDING_INVALID`, because each conjunct maps to exactly one column or
  key of the datastore.
- Keywords (`where`, `and`, `in`, `true`, `false`) are lowercase and
  case-sensitive. Whitespace between tokens is optional.
- Only `=` and `and` are **active**. The reserved operators &mdash; `!=`, `<`,
  `<=`, `>`, `>=`, `in` &mdash; are recognized by the tokenizer and rejected
  with `WHERE_OPERATOR_UNSUPPORTED`.

### Right-hand sides

Each `<rhs>` is one of:

| Form | Examples | Notes |
| --- | --- | --- |
| Symbol | `$categorySlug`, `$principal.sub` | `$` plus a bound name, optionally followed by a dotted path that is walked into the bound value at runtime. |
| String | `'open'`, `"open"`, `'it\'s'`, `"a\\b"` | Single or double quotes; a backslash escapes the next character. `and`, `where`, `$` and `=` inside quotes are literal text. |
| Number | `3`, `-2`, `+7`, `1.5`, `.5`, `3.`, `1e3`, `2.5E-2` | Optional sign, decimals and exponent. An integer lexeme binds as `int`; every other form binds as `float`. |
| Boolean | `true`, `false` | Lowercase only. |

Anything else in `<rhs>` position &mdash; a bare identifier, an unterminated
quote &mdash; aborts with `WHERE_RHS_INVALID`.

### Symbol scope

Every `$`-sigil right-hand side resolves through the shared v0.3
[symbol resolution](./symbol-resolution.md) model. The scope is exactly the
namespace the runtime builds for the predicate fetch:

- the **route slugs** &mdash; every `{name}` in the controller `base_path` plus
  the route `path`;
- the names this rule binds in `given:` through an **`identity:`** or
  **`request`** binding.

Document bindings of the same rule are **not** in scope &mdash; neither the
plain `<collection>[ by <param>]` bindings nor the `where` bindings, including
the binding being defined. Their records are what the fetch produces, so nothing
is bound under those names when the predicate is evaluated. Referencing one, or
any unknown name, aborts with the single `UNDEFINED_SYMBOL` error:

```
symbol $ghost is not bound in scope controller 'assets' route 'listAssets' access[0] given 'category' where
```

At runtime an `identity:` or `request` name shadows a route slug of the same
name.

### Field check

The `<field>` of every conjunct must be declared on the entity behind the
collection's repository; `fields` are merged along the entity's `extends`
chain. An unknown field aborts generation with `WHERE_FIELD_UNKNOWN`. The check
is skipped when the collection has no repository or its entity is not declared.

## Errors

All errors carry the path `controllers.<controller>.routes.<route>.access[<i>].given.<symbol>`.

| Code | Cause | Message |
| --- | --- | --- |
| `WHERE_BINDING_INVALID` | Grammar fault: missing `where` or `=`, dotted field, trailing tokens | `Invalid where binding: '<raw>'. Expected <what> at column <n>, found <token>` (hint carries the grammar) |
| `WHERE_OPERATOR_UNSUPPORTED` | A reserved operator | `where operator '<op>' is reserved but not implemented; only '=' is active in v0.3` |
| `WHERE_RHS_INVALID` | `<rhs>` is not a symbol, string, number or boolean | `Invalid right-hand side <token> at column <n> in where binding '<raw>'` |
| `WHERE_FIELD_UNKNOWN` | `<field>` not declared on the collection's entity | `where field '<field>' is not declared on collection '<collection>'` |
| `UNDEFINED_SYMBOL` | `$<name>` not in the rule's scope | `symbol $<name> is not bound in scope <label>` |

Columns are 1-based; `<token>` is the offending lexeme or `end of binding`.

## Runtime semantics

### Fetched per rule, before the rule runs

Once the principal is resolved, every `where` binding of every rule on the route
is fetched with `find_one(collection, criteria)`, where `criteria` maps each
`<field>` to its evaluated `<rhs>`. Each rule gets its own mapping of symbol to
record, so the same symbol name may be bound differently in two rules without
collision. An unauthenticated request fetches nothing and is rejected with `401`
as usual.

These semantics apply equally to `yaml-api run` and to standalone FastAPI, raw
ASGI and Django REST Framework backends produced by `yaml-api build`. Generated
routes retain the binding's collection and complete predicate, inject or create
that collection's repository, and perform the lookup before evaluating the rule.
Generated applications do not import the generator package at runtime.

### A miss makes the rule fail

A predicate that matches **no record** makes that rule not match &mdash; for an
`allow` rule and a `deny` rule alike. Evaluation moves on to the next rule; when
no rule allows the request, the response is the ordinary `403`. There is no
`404` for a `where` miss: "no such record" and "a record you may not act on" are
deliberately indistinguishable, so the route cannot be used as an existence
oracle for the bound collection. A record that is found but fails the rule's
`when:` is a `403` as well.

Downstream fetch steps are unchanged: on `get`, `update`, `replace` and `delete`
an authorized caller still receives `404` when the `{id}` target does not exist.

### Replaces the implicit fetch

When every document binding on the route uses the `where` form, no record is
fetched for authorization other than the `where` targets, and the rules are
evaluated before the operation runs. A rule that also keeps a plain
`<collection>[ by <param>]` binding, or whose `when:` reads the operation's own
record, is still evaluated after that record is fetched, with its `where`
documents available.

## Custom repositories

In the development server the fetch goes through
`BaseRepository.find_one(collection_name, criteria)`, an abstract method
returning one matching record or `None`. Generated repositories expose the
equivalent collection-specific `find_one(criteria)` operation. The generated
SQL repository issues `SELECT ... WHERE <field> = <value> [AND ...] LIMIT 1`;
the generated MongoDB repository passes `criteria` as the filter. A custom
development-server repository must implement the abstract method, and a custom
generated repository must retain the collection-specific operation.

## v0.2 is unchanged

The `where` binding form is available only under `version: "0.3"`. A
`version: "0.2"` document binding (`<collection>` or `<collection> by <param>`)
keeps its implicit primary-key / `{id}` fetch and existing behavior; the word
`where` carries no special meaning in v0.2.
