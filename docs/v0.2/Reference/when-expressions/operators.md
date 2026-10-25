---
title: "When Expression Operators"
description: All operators available in when expressions for ownership and ABAC access rules.
---

Defines all operators available in `when:` expressions for ownership and ABAC access rules.

A `when:` expression appears inside an access-rule object on a controller. It compares
field references (the principal and a bound document) using the operators below and
decides whether the rule matches.

> **Enforcement**
>
> Roles, role hierarchies, `<entity>:*` scoping, and ownership/ABAC `when` rules
> are enforced by the generated FastAPI backend, the generated DRF backend, and the
> `stackform run` dev server alike. A request that no rule admits gets 401 when it
> carries no valid credentials and 403 otherwise; a missing record answers 404
> before ownership is checked.

## Comparison Operators

### `equals`

Returns `true` if the left operand equals the right operand. Use the word `equals`,
not `==`.

```yaml
when: principal.sub equals document.authorId
when: document.status equals 'published'
when: principal.record.role equals 'admin'
```

### `not equals`

Returns `true` if the left operand does not equal the right operand.

```yaml
when: principal.sub not equals document.authorId
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

## Null Tests

### `is null`

Returns `true` if the field is absent or holds `null`.

```yaml
when: document.archivedAt is null
```

### `is not null`

Returns `true` if the field holds a value.

```yaml
when: principal.record.verifiedAt is not null
```

## Logical Operators

### `and`

Returns `true` if both operands are true.

```yaml
when: principal.sub equals document.ownerId and document.status equals 'active'
```

### `or`

Returns `true` if either operand is true.

```yaml
when: principal.record.role equals 'admin' or principal.sub equals document.ownerId
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

So `A or B and C` is parsed as `A or (B and C)`. Parentheses override precedence:

```yaml
when: (document.status equals 'draft' or document.status equals 'review') and principal.sub equals document.authorId
```

## List Syntax (Implicit AND)

A YAML list of expressions is ANDed together:

```yaml
when:
  - principal.sub equals document.authorId
  - document.status not in ['deleted']
```

Is equivalent to:

```yaml
when: principal.sub equals document.authorId and document.status not in ['deleted']
```

## Operands

The only operands are field references and single-quoted string literals.

### Field references

A field reference is a dotted path rooted at a symbol bound in the rule's `given:`.
The paths below assume `given: { principal: identity:user, document: <collection> }`;
the names are the author's choice.

| Path | Description |
|------|-------------|
| `principal.sub` | The bound identity's subject id (the `sub` claim), as a string. |
| `principal.record.fieldName` | A field on the identity's stored record (the identity document, with `_auth` and `password` removed). |
| `document.fieldName` | A field on the document the symbol is bound to (the record being read or written). |

A field reference always has at least one `.`; a bare symbol such as `principal` is
rejected with `WHEN_OPERAND_INVALID`. There are no built-in roots. Every root
referenced here MUST be declared in `given:`, or generation aborts with
`WHEN_UNBOUND_SYMBOL`. `principal` and `document` are
conventional names, not keywords -- name your symbols whatever you like in `given:`
and reference those names.

### String literals

A string literal is single-quoted: `'admin'`. Double quotes are not a string-literal
form here and do not work.

### Right operands

| Type | Syntax | Example |
|------|--------|---------|
| Field reference | `document.ownerId` | `principal.sub equals document.ownerId` |
| String literal | `'admin'` | `document.status equals 'published'` |
| List of strings | `['a', 'b']` | `principal.record.role in ['admin', 'moderator']` |

## Edge Cases

- **Keywords are case-insensitive.** `equals`, `not`, `and`, `or`, `in`, `is null` may be written
  in any case (`EQUALS`, `And`, and so on are all accepted). Lowercase is the
  conventional, readable form.

- **String literals are single-quoted.** `'admin'` is the supported form. Use
  `equals 'admin'`, never `equals "admin"` and never `== 'admin'`.

- **There are no boolean literals.** `true` and `false` are not valid operands and
  cause `WHEN_OPERAND_INVALID`. To test a boolean stored field, compare against a
  string the data uses, or model the flag as an enum/string and compare that.

- **Missing fields resolve to null.** A field path that points at a key not present on
  the record resolves to `null`. Two `null` values compare equal; `null` never equals
  a string. Test for it with `is null` / `is not null`.

- **`not` negates a comparison, not a bare field.** Write `not document.status equals 'archived'`.
  A bare field reference is not a truth test: it never matches, so
  `not document.published` always does. Use `is null`, `is not null`, or an explicit
  comparison.

- **`in []` (empty list).** Always returns `false`; no value is a member of an empty
  list. **`not in []`** correspondingly always returns `true`.

## See Also

- [When expressions overview](./overview.md)
- [Access control](../controllers/access-control.md)
