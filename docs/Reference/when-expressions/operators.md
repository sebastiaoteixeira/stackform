---
title: "Reference: When Expression Operators"
description: Defines all operators available in `when:` expressions for ABAC access rules.
---

# Reference: When Expression Operators

Defines all operators available in `when:` expressions for ABAC access rules.

## Comparison Operators

### `equals`

Returns `true` if the left operand equals the right operand.

```yaml
when: principal.sub equals document.authorId
when: document.status equals 'published'
when: principal.record.active equals true
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
when: principal.record.role in ['admin', 'moderator']
when: document.status in ['draft', 'published']
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
when: principal.sub equals document.ownerId and document.active equals true
```

### `or`

Returns `true` if either operand is true.

```yaml
when: principal.record.role equals 'admin' or principal.record.role equals 'moderator'
```

### `not`

Negates the following expression.

```yaml
when: not document.published
when: not principal.record.active equals true
```

## Operator Precedence

From highest to lowest:

1. `not` (tightest binding)
2. `and`
3. `or` (loosest binding)

So `A or B and C` is parsed as `A or (B and C)`.

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

## Operand Types

### Left operands

Field paths referencing bound values:

| Path | Description |
|------|-------------|
| `principal.sub` | Principal's primary key value (string). |
| `principal.record.fieldName` | Field on the principal's entity record. |
| `document.fieldName` | Field on the loaded document. |

### Right operands

| Type | Syntax | Example |
|------|--------|---------|
| Field path | `document.ownerId` | `principal.sub equals document.ownerId` |
| String literal | `'admin'` (single quotes only) | `document.status equals 'published'` |
| Boolean literal | `true`, `false` | `principal.record.active equals true` |
| List literal | `['a', 'b']` (single-quoted items) | `principal.record.role in ['admin', 'moderator']` |

## Edge Cases

- **Keywords are case-sensitive.** `equals`, `not`, `and`, `or`, `in` must be lowercase. Uppercase variants are not recognized.

- **String literals require single quotes.** `'admin'` is valid. `"admin"` is NOT valid and causes a parse error.

- **`null` comparisons.** If a field path resolves to a non-existent field, the value is `null`. `null equals null` returns `true`. `null equals 'anything'` returns `false`.

- **`in []` (empty list).** Always returns `false`. No value is a member of an empty list.

- **`not in []` (empty list).** Always returns `true`. Every value is not in an empty list.

- **`in` list items must be single-quoted strings.** `['admin', 'moderator']` is valid. `[admin, moderator]` without quotes is not valid.

- **Boolean `true`/`false` in comparisons.** `equals true` and `equals false` compare against boolean values. The literal keywords `true` and `false` are recognized without quotes.

- **`not` placement.** `not` precedes the expression it negates: `not document.published`, `not principal.record.active equals true`.

## See Also

- [When expressions overview](./overview.md)
- [Access control](../controllers/access-control.md)
