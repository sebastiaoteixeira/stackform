---
title: "When Expression Operators"
description: All operators available in when expressions for ownership and ABAC access rules.
---

Defines all operators available in `when:` expressions for ownership and ABAC access rules.

A `when:` expression appears inside an access-rule object on a controller. It compares
field references (the principal and a bound document) using the operators below and
decides whether the rule matches.

> **Enforcement status**
>
> Roles (exact match), `identity:<entity>` scoping, and ownership/ABAC `when` rules
> are enforced by the generated FastAPI backend, the generated DRF backend, and the
> `yaml-api run` dev server alike. A request that fails a rule gets 401 (missing or
> invalid credentials), 403 (authenticated but not allowed), or 404 (record not
> found, checked before ownership). Two current limitations: role hierarchy (for
> example `admin` inheriting `moderator`) is accepted in YAML but not yet applied
> during enforcement -- only exact role matches are checked; and conditional or
> ownership rules require a v0.2 spec, because v0.1 specs do not parse `when` rules.

## Comparison Operators

### `equals`

Returns `true` if the left operand equals the right operand. Use the word `equals`,
not `==`.

```yaml
when: principal equals document.authorId
when: document.status equals 'published'
when: principal.record.role equals 'admin'
```

### `not equals`

Returns `true` if the left operand does not equal the right operand.

```yaml
when: principal not equals document.authorId
when: document.status not equals 'archived'
```

## Membership Operators

### `in`

Returns `true` if the left operand is a member of the right-hand list.

```yaml
when: document.status in ['draft', 'published']
when: principal.record.role in ['admin', 'moderator']
```

### `not in`

Returns `true` if the left operand is not a member of the right-hand list.

```yaml
when: document.status not in ['deleted', 'archived']
when: principal.record.plan not in ['free']
```

## Logical Operators

### `and`

Returns `true` if both operands are true.

```yaml
when: principal equals document.ownerId and document.status equals 'active'
```

### `or`

Returns `true` if either operand is true.

```yaml
when: principal.record.role equals 'admin' or principal equals document.ownerId
```

### `not`

Negates the following comparison.

```yaml
when: not document.status equals 'archived'
```

## Operator Precedence

From highest to lowest:

1. `not` (tightest binding)
2. `and`
3. `or` (loosest binding)

So `A or B and C` is parsed as `A or (B and C)`.

There is no parenthesis grouping. Reach for the YAML-list form below when you need to
combine clauses without relying on precedence.

## List Syntax (Implicit AND)

A YAML list of expressions is ANDed together:

```yaml
when:
  - principal equals document.authorId
  - document.status not in ['deleted']
```

Is equivalent to:

```yaml
when: principal equals document.authorId and document.status not in ['deleted']
```

## Operands

The only operands are field references and single-quoted string literals.

### Field references

A field reference is a dotted path rooted at a bound symbol.

| Path | Description |
|------|-------------|
| `principal` | The principal's subject id (the `sub` claim), as a string. A bare `principal` resolves to this. |
| `principal.sub` | Same value as bare `principal` written explicitly. |
| `principal.record.fieldName` | A field on the principal's stored record (the identity document, with `_auth` and `password` removed). |
| `document.fieldName` | A field on the document loaded for this request (the record being read or written). |

The built-in roots `principal` and `document` are bound automatically. If you declare
custom symbol names with `given:` on the access rule, reference those names instead.

### String literals

A string literal is single-quoted: `'admin'`. Double quotes are not a string-literal
form here and do not work.

### Right operands

| Type | Syntax | Example |
|------|--------|---------|
| Field reference | `document.ownerId` | `principal equals document.ownerId` |
| String literal | `'admin'` | `document.status equals 'published'` |
| List of strings | `['a', 'b']` | `principal.record.role in ['admin', 'moderator']` |

## Edge Cases

- **Keywords are case-insensitive.** `equals`, `not`, `and`, `or`, `in` may be written
  in any case (`EQUALS`, `And`, and so on are all accepted). Lowercase is the
  conventional, readable form.

- **String literals are single-quoted.** `'admin'` is the supported form. Use
  `equals 'admin'`, never `equals "admin"` and never `== 'admin'`.

- **There are no boolean literals.** `true` and `false` are not valid operands and
  cause a parse error. To test a boolean stored field, compare against a string the
  data uses, or model the flag as an enum/string and compare that.

- **Missing fields resolve to nothing.** If a field path points at a key that is not
  present on the record, it resolves to an absent value. Two absent values compare
  equal to each other; an absent value never equals a string. There is no `null`
  literal you can write yourself -- absence only arises from a missing field.

- **`not` negates a comparison, not a bare field.** Write `not document.status equals 'archived'`.
  A bare field reference (for example `not document.published`) is not a truth test and
  does not check whether the field is set; prefer an explicit comparison such as
  `document.published equals 'true'` against the value your data stores.

- **`in []` (empty list).** Always returns `false`; no value is a member of an empty
  list. **`not in []`** correspondingly always returns `true`.

## See Also

- [When expressions overview](./overview.md)
- [Access control](../controllers/access-control.md)
