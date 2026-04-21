# Reference: When Expressions

`when:` expressions are used in ABAC access rules to evaluate conditions against the authenticated principal and/or a loaded document.

## Context

`when:` only makes sense inside a `given:` block that binds `principal` and/or `document`:

```yaml
access:
  - given:
      principal: identity:user
      document: posts
    when: principal.sub equals document.authorId
```

## Field paths

Values in expressions are referenced by dot-path:

| Path | Description |
|------|-------------|
| `principal.sub` | The principal's identifier value (the `identifier` field value) |
| `principal.record.fieldName` | Any field on the principal's entity record |
| `document.fieldName` | Any field on the loaded document |

## List syntax

A list of expressions is ANDed together:

```yaml
when:
  - principal.sub equals document.authorId
  - document.status not equals 'archived'
```

Is equivalent to:

```yaml
when: principal.sub equals document.authorId and document.status not equals 'archived'
```

## Literal values

String literals use single quotes: `'admin'`, `'active'`.

List literals use bracket syntax: `['admin', 'moderator']`.

## Operators

See [operators](./operators.md) for the full list.

## Example expressions

```yaml
when: principal.sub equals document.authorId
when: principal.record.role equals 'admin'
when: principal.record.role in ['admin', 'moderator']
when: document.status not in ['deleted', 'archived']
when: principal.sub equals document.ownerId and document.active equals true
when: not document.published
```

## Short-circuit and fallback patterns

Rules are evaluated top-to-bottom and the first match wins. Common patterns:

### Allow owner or role

```yaml
access:
  - moderator
  - given:
      principal: identity:user
      document: posts
    when: principal.sub equals document.authorId
```

Moderator check first (cheap, no document load). Owner check second.

### Deny non-authors, allow everyone else

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
