# Reference: Access Control

Determines who is allowed to call each route, declared on controllers and individual operations.

## Syntax

### Simple values

```yaml
access: public              # no auth required
access: "*"                 # any authenticated principal
access: user:*              # any principal from the user entity
access: admin               # principal with admin role (single auth entity)
access: user:admin          # principal with admin role (explicit entity)
```

### List of rules

```yaml
access:
  - moderator
  - given:
      principal: identity:user
      document: posts
    when: principal.sub equals document.authorId
    then: allow
```

### ABAC rule with deny

```yaml
access:
  - admin
  - given:
      principal: identity:user
      document: posts
    when: principal.sub not equals document.authorId
    then: deny
  - then: allow
```

## Behavior

- **Parse time:** Access values are parsed and validated. Entity names in scoped roles are checked against declared auth entities. Unscoped role names with multiple auth entities raise `ACCESS_AMBIGUOUS_ROLE`.
- **Runtime:** Rules are evaluated top-to-bottom. The first matching rule determines the outcome (allow or deny). If no rule matches, the request is denied (implicit deny).

## Options

### Access value types

| Value | Description |
|-------|-------------|
| `public` | No authentication required. Any request is allowed. |
| `"*"` | Any authenticated principal from any auth entity. Returns 401 if no valid credentials. |
| `entityName:*` | Any authenticated principal from a specific auth entity. |
| `roleName` | Principal with this role (single auth entity only; entity prefix optional). |
| `entityName:roleName` | Principal with this role from a specific entity (required with multiple auth entities). |
| list | Multiple rules evaluated top-to-bottom. |

### ABAC rule fields (`given`/`when`/`then`)

| Field | Required | Type | Description |
|-------|----------|------|-------------|
| `given.principal` | no | `identity:<entityName>` | Binds the authenticated principal. |
| `given.document` | no | string (repository name) | Loads the target document for condition evaluation. |
| `when` | no | string or list of strings | Condition expression. List entries are ANDed. See [when expressions](../when-expressions/overview.md). |
| `then` | no | `"allow"` (default) or `"deny"` | Effect when the rule matches. |

Both `principal` and `document` in `given` are optional, but at least one must be present for a `when:` condition.

## Evaluation Order

1. Rules in the `access:` list are evaluated top-to-bottom.
2. The first matching rule wins (whether `allow` or `deny`).
3. If no rule matches, the request is denied (implicit deny).

## Controller vs Operation Precedence

Operation-level `access:` completely replaces the controller-level `access:` for that operation. There is no merging.

```yaml
controllers:
  posts:
    access: public           # default for all operations
    operations:
      create: { access: "*" }   # overrides: only authenticated users
      # list, get use access: public (inherited from controller)
```

## 401 vs 403

| Status | Condition |
|--------|-----------|
| 401 Unauthorized | Credentials are missing or invalid (not authenticated). |
| 403 Forbidden | Credentials are valid but the principal does not satisfy the access rule (not authorized). |

## Examples

### Public read, authenticated write

```yaml
controllers:
  posts:
    access: public
    operations:
      create: { access: "*" }
      update: { access: "*" }
      delete: { access: "*" }
```

### Role-based with owner override

```yaml
controllers:
  posts:
    access: public
    operations:
      update:
        access:
          - moderator
          - given:
              principal: identity:user
              document: posts
            when: principal.sub equals document.authorId
```

Moderators pass the first rule (no document load). Authors pass the second rule.

### Deny pattern: block non-authors

```yaml
update:
  access:
    - admin
    - given:
        principal: identity:user
        document: posts
      when: principal.sub not equals document.authorId
      then: deny
    - then: allow
```

Rule 1: admins pass immediately. Rule 2: non-authors are denied. Rule 3: everyone else (the author) reaches the fallback `then: allow`.

### Multiple auth entities

When multiple auth entities exist (e.g., `user` and `apiClient`), the entity prefix is required on role-based access rules. If both entities define an `admin` role, writing `access: admin` is ambiguous -- the engine does not know which entity you mean. `user:admin` eliminates the ambiguity. Using an unscoped role name with multiple auth entities raises `ACCESS_AMBIGUOUS_ROLE` at parse time.

```yaml
controllers:
  resources:
    operations:
      delete:
        access:
          - user:moderator
          - apiClient:enterprise
          - given:
              principal: identity:user
              document: resources
            when: principal.sub equals document.ownerId
```

## Edge Cases

- **Rules evaluated top to bottom.** The first matching rule determines the outcome. Place cheap checks (role-based, no DB lookup) before document-level checks.

- **No rule matches: implicit deny.** If no rule in the list matches, the request is denied. Unauthenticated requests get 401; authenticated requests get 403.

- **`then: allow` is the default.** If `then:` is omitted in a `given`/`when` rule, it defaults to `allow`.

- **`then: deny` explicitly denies.** Useful for "everyone except X" patterns. If the `when` condition matches, the request is denied.

- **`given` without `when`.** Matches whenever the `given` bindings are satisfied. For example, `given: { principal: identity:user }` with no `when:` matches any authenticated user from the `user` entity.

- **`given` with `document:` binding.** The document is fetched BEFORE the rule is evaluated. If the document does not exist (e.g., wrong ID), the rule is skipped (not denied).

- **`create` operations have no document.** On `create`, there is no existing document. Rules with `document:` bindings are skipped for create. Use principal-only rules for create access.

- **Controller-level `access:` is the default.** Per-operation `access:` overrides it completely. There is no merging of controller and operation access rules.

- **Inline list syntax.** `access: "[user:admin, user:moderator]"` is parsed as a YAML string. The engine parses the bracket notation into a list of rules.

## Errors

| Condition | Error code | Message |
|-----------|-----------|---------|
| Unknown entity in scoped role | `ACCESS_UNKNOWN_ENTITY` | "Unknown auth entity 'X' in access rule" |
| Unscoped role with multiple auth entities | `ACCESS_AMBIGUOUS_ROLE` | "Unscoped role 'X' is ambiguous with multiple auth entities" |
| Role used with no auth entities defined | `ACCESS_NO_AUTH_ENTITY` | "Cannot use role 'X' without auth entities" |

## See Also

- [When expressions](../when-expressions/overview.md)
- [When operators](../when-expressions/operators.md)
- [Roles overview](../roles/overview.md)
- [Auth overview](../auth/overview.md)
