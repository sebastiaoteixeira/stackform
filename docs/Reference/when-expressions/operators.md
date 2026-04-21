# Reference: When Expression Operators

## Comparison operators

### `equals`

True when the left operand equals the right operand.

```yaml
when: principal.sub equals document.authorId
when: document.status equals 'published'
when: principal.record.active equals true
```

### `not equals`

True when the left operand does not equal the right operand.

```yaml
when: principal.sub not equals document.authorId
when: document.status not equals 'archived'
```

## Membership operators

### `in`

True when the left operand is a member of the right-hand list.

```yaml
when: principal.record.role in ['admin', 'moderator']
when: document.status in ['draft', 'published']
```

### `not in`

True when the left operand is not a member of the right-hand list.

```yaml
when: document.status not in ['deleted', 'archived']
when: principal.record.plan not in ['free']
```

## Logical operators

### `and`

True when both operands are true.

```yaml
when: principal.sub equals document.ownerId and document.active equals true
```

### `or`

True when either operand is true.

```yaml
when: principal.record.role equals 'admin' or principal.record.role equals 'moderator'
```

### `not`

Negates the following expression.

```yaml
when: not document.published
when: not principal.record.active equals true
```

## Operator precedence

`not` binds tightest, then `and`, then `or`. Use parentheses for explicit grouping (if supported by the expression parser).

## List syntax (implicit AND)

```yaml
when:
  - principal.sub equals document.authorId
  - document.status not in ['deleted']
```

Is equivalent to:

```yaml
when: principal.sub equals document.authorId and document.status not in ['deleted']
```

## Operand types

Left operands are field paths (`principal.sub`, `document.authorId`, `principal.record.role`).

Right operands are:
- Field paths: `document.ownerId`, `principal.sub`
- String literals: `'admin'`, `'published'` (single quotes)
- Boolean literals: `true`, `false`
- List literals: `['admin', 'moderator']` (for `in` / `not in`)
