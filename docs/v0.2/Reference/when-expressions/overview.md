---
title: "When Expressions"
description: Conditional expressions evaluated against the authenticated principal and a fetched document inside ABAC access rules.
---

Conditional expressions evaluated against the authenticated principal and a fetched document inside ABAC access rules. A `when:` expression turns a static role/identity rule into an ownership or attribute check (for example, "the requester is the owner of this record").

> **Enforcement status**
>
> Roles (exact match), `<entity>:*` scoping, and ownership/ABAC `when` rules
> are enforced by the generated FastAPI backend, the generated DRF backend, and the
> `yaml-api run` dev server alike. A request that fails a rule gets 401 (missing or
> invalid credentials), 403 (authenticated but not allowed), or 404 (record not
> found, checked before ownership). Two current limitations: role hierarchy (for
> example `admin` inheriting `moderator`) is accepted in YAML but not yet applied
> during enforcement -- only exact role matches are checked; and conditional or
> ownership rules require a v0.2 spec, because v0.1 specs do not parse `when` rules.

## Syntax

`when:` appears inside an access-rule object. The rule's `given:` block binds the symbol names your expression references:

```yaml
api: { basePath: /api, version: v1 }   # routes are served under /api/v1/...

controllers:
  myCollection:
    access:
      - given:
          principal: identity:user
          document: myCollection
        when: principal.sub equals document.ownerId
```

`given:` is a map of symbol-name to binding. A binding is either:

- `identity:<entity>` -- binds the symbol to the authenticated principal of that auth entity.
- `<collection>` or `<collection> by <param>` -- binds the symbol to the route's document (the record being read or written), optionally looked up by a path parameter.

The symbol names are free-form. The example above uses `principal` and `document`, but you can name them anything:

```yaml
when:
  - given:
      requester: identity:user
      record: myCollection
    when: requester.sub equals record.ownerId
```

In addition, `principal` and `document` are always available as built-in roots even without a `given:` entry: `principal` resolves to the authenticated principal, and `document` resolves to the fetched record. Naming a symbol `principal`/`document` in `given:` simply makes the binding explicit.

### String form

```yaml
when: principal.sub equals document.ownerId
```

### List form (implicit AND)

```yaml
when:
  - principal.sub equals document.ownerId
  - document.status not equals 'archived'
```

A list of expressions is ANDed together. Equivalent to:

```yaml
when: principal.sub equals document.ownerId and document.status not equals 'archived'
```

## Evaluation

- **Parse time:** Expression strings are parsed into an expression tree. Invalid syntax aborts generation with a `WHEN_*` error (exit 1).
- **Runtime:** The expression is evaluated against the bound principal and document. It returns true or false, which combines with the rule's `then: allow|deny` effect.
- **When a document is involved:** Any rule whose `when` references a document (the built-in `document` root or a document symbol from `given:`) is evaluated after the record is fetched. For `get`/`update`/`replace`/`delete`, the record is loaded first; a missing record returns 404 before the ownership check runs. `create` has no fetched document, so document-dependent rules do not apply to it.

## Field Paths

| Path | Description |
|------|-------------|
| `principal` | Bare reference (no `.`) resolves to the principal's primary-key value (its `sub`). |
| `principal.sub` | The principal's primary-key value (string). |
| `principal.roles` | The principal's role list (loaded from the auth record's `roles`/`role` field). |
| `principal.record.fieldName` | Any field on the principal's stored record. Stored fields live under `record`, not directly on `principal`. |
| `document.fieldName` | A field on the fetched document. Only meaningful when the rule binds a document. |

Field paths follow the symbol names you chose in `given:`. If you bind `requester: identity:user`, then write `requester.sub` and `requester.record.email`.


## Operands and Literals

Operands are either field references (as above) or single-quoted string literals:

- **String literals:** Single quotes only: `'admin'`, `'active'`. Double quotes are not supported and cause a parse error.
- **List literals:** `['admin', 'moderator']` for use with `in` / `not in`.

There are no numeric or boolean literals. Compare against single-quoted strings instead (for example, `document.status equals 'published'`, not `document.published equals true`).

## Operators

See [operators](./operators.md) for the complete reference.

| Operator | Example |
|----------|---------|
| `equals` | `principal.sub equals document.ownerId` |
| `not equals` | `document.status not equals 'archived'` |
| `in` | `principal.record.role in ['admin', 'moderator']` |
| `not in` | `document.status not in ['deleted', 'archived']` |
| `and` | `A and B` |
| `or` | `A or B` |
| `not` | `not A` |

Use the operator words; `==` and `!=` are not recognized. Operator and keyword matching is case-insensitive, so `equals`, `Equals`, and `EQUALS` are all accepted (lowercase is the convention used throughout these docs).

## Examples

```yaml
when: principal.sub equals document.ownerId
when: principal.record.role equals 'admin'
when: principal.record.role in ['admin', 'moderator']
when: document.status not in ['deleted', 'archived']
when: principal.sub equals document.ownerId and document.status equals 'active'
when: not document.locked
```

### Allow owner or role

```yaml
api: { basePath: /api, version: v1 }

controllers:
  myCollection:
    access:
      - moderator
      - given:
          principal: identity:user
          document: myCollection
        when: principal.sub equals document.ownerId
```

The bare-role rule is checked first (no document load). If it does not match, the ownership rule loads the record and allows the owner.

### Deny non-owners, allow everyone else

```yaml
api: { basePath: /api, version: v1 }

controllers:
  myCollection:
    access:
      - given:
          principal: identity:user
          document: myCollection
        when: principal.sub not equals document.ownerId
        then: deny
      - then: allow
```

Non-owners are denied. The owner falls through to the trailing `then: allow`.

## Edge Cases

- **Missing principal field.** `principal.record.X` where `X` does not exist resolves to `null`. `null equals null` is true; `null equals 'anything'` is false.

- **Missing document field.** `document.X` where `X` does not exist resolves to `null`.

- **Precedence.** `not` binds tightest, then `and`, then `or`. So `A or B and C` means `A or (B and C)`. There is no parenthesis grouping; split complex logic into the list form instead.

- **`principal.sub` type.** Always a string (the principal's primary-key value, stringified).

- **`in []` (empty list).** Always false. **`not in []`** is always true.

- **String literals must be single-quoted.** `'admin'` is valid; `"admin"` is a parse error.

- **List syntax `when: [expr1, expr2]`.** ANDs the expressions together, equivalent to `when: "expr1 and expr2"`.

## Errors

| Code | Condition |
|------|-----------|
| `WHEN_EXPR_INVALID` | Empty expression or an unexpected token after a complete expression. |
| `WHEN_OPERAND_MISSING` | An operator with no following operand. |
| `WHEN_OPERAND_INVALID` | An operand that is neither a field reference nor a single-quoted string. |
| `WHEN_LIST_INVALID` | A malformed `[...]` list for `in` / `not in`. |
| `DOCUMENT_BINDING_INVALID` | A `given:` document binding that is not `<collection>` or `<collection> by <param>`. |
| `ACCESS_UNKNOWN_ENTITY` | A `given:` `identity:<entity>` naming an entity that is not a `type: auth` entity. |

## See Also

- [Operators](./operators.md)
- [Access control](../controllers/access-control.md)
