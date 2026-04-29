---
title: "When Expressions"
description: Evaluates conditions against the authenticated principal and/or a loaded document inside ABAC access rules.
---

Evaluates conditions against the authenticated principal and/or a loaded document inside ABAC access rules.

## Syntax

`when:` only appears inside a `given:` block that binds `principal` and/or `document`:

```yaml
access:
  - given:
      principal: identity:user
      document: posts
    when: principal.sub equals document.authorId
```

### String form

```yaml
when: principal.sub equals document.authorId
```

### List form (implicit AND)

```yaml
when:
  - principal.sub equals document.authorId
  - document.status not equals 'archived'
```

A list of expressions is ANDed together. Equivalent to:

```yaml
when: principal.sub equals document.authorId and document.status not equals 'archived'
```

## Behavior

- **Parse time:** Expression strings are parsed into an AST. Invalid syntax raises a parse error.
- **Runtime:** The expression is evaluated against the bound `principal` and `document` objects. Returns `true` or `false`.

## Field Paths

| Path | Description |
|------|-------------|
| `principal.sub` | The principal's primary key value (string). |
| `principal.record.fieldName` | Any field on the principal's entity record (with `_auth` stripped). |
| `document.fieldName` | Any field on the loaded document. Only available when `given` has a `document:` binding. |

## Literal Values

- **String literals:** Must use single quotes: `'admin'`, `'active'`. Double quotes are NOT supported.
- **Boolean literals:** `true`, `false`.
- **List literals:** `['admin', 'moderator']` -- items must be single-quoted strings.

## Operators

See [operators](./operators.md) for the complete reference.

| Operator | Example |
|----------|---------|
| `equals` | `principal.sub equals document.authorId` |
| `not equals` | `document.status not equals 'archived'` |
| `in` | `principal.record.role in ['admin', 'moderator']` |
| `not in` | `document.status not in ['deleted', 'archived']` |
| `and` | `A and B` |
| `or` | `A or B` |
| `not` | `not document.published` |

## Examples

```yaml
when: principal.sub equals document.authorId
when: principal.record.role equals 'admin'
when: principal.record.role in ['admin', 'moderator']
when: document.status not in ['deleted', 'archived']
when: principal.sub equals document.ownerId and document.active equals true
when: not document.published
```

### Short-circuit patterns

#### Allow owner or role

```yaml
access:
  - moderator
  - given:
      principal: identity:user
      document: posts
    when: principal.sub equals document.authorId
```

Moderator check first (cheap, no document load). Owner check second.

#### Deny non-authors, allow everyone else

```yaml
access:
  - given:
      principal: identity:user
      document: posts
    when: principal.sub not equals document.authorId
    then: deny
  - then: allow
```

Non-authors are denied. The author reaches the fallback `then: allow`.

## Edge Cases

- **Operator keywords are case-sensitive.** `and`, `or`, `not`, `equals`, `in` must be lowercase. `AND`, `OR`, `NOT` are not recognized.

- **Precedence.** `not` binds tightest, then `and`, then `or`. So `A or B and C` means `A or (B and C)`.

- **`principal.sub` type.** Always a string (the user's primary key value, stringified).

- **`principal.record.X` where X does not exist.** Evaluates to `null`. `null equals null` is `true`. `null equals 'anything'` is `false`.

- **`document.X` where X does not exist.** Evaluates to `null`.

- **`document.X` without document binding.** If `given` does not include a `document:` binding, referencing `document.X` in `when` causes the rule to be skipped (treated as non-matching).

- **String literals must be single-quoted.** `'admin'` is valid. `"admin"` is NOT supported and will cause a parse error.

- **`in []` (empty list).** Always evaluates to `false`.

- **`not in []` (empty list).** Always evaluates to `true`.

- **List syntax `when: [expr1, expr2]`.** ANDs the expressions together. Equivalent to `when: "expr1 and expr2"`.

## Errors

| Condition | Error |
|-----------|-------|
| Invalid expression syntax | Parse error at the expression position |
| Unknown field path prefix | Parse error (only `principal` and `document` are valid roots) |

## See Also

- [Operators](./operators.md)
- [Access control](../controllers/access-control.md)
