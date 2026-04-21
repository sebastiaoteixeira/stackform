# Reference: Access Control

Access rules are declared on controllers and individual operations. They determine who is allowed to call each route.

## Access value types

### `public`

No authentication required. Any request is allowed.

```yaml
access: public
```

### `"*"`

Any authenticated principal. The principal can be from any auth entity.

```yaml
access: "*"
```

Returns 401 if no valid credentials are provided.

### Entity-scoped any: `entityName:*`

Any authenticated principal from a specific auth entity.

```yaml
access: user:*
access: apiClient:*
```

### Role: `roleName` or `entityName:roleName`

Authenticated principal with a specific role (or a role that includes it via hierarchy).

```yaml
# Single auth entity: prefix optional
access: admin
access: moderator

# Multiple auth entities: prefix required
access: user:admin
access: apiClient:enterprise
```

With a single auth entity, the entity prefix can be omitted. With multiple auth entities, omitting the prefix is a validation error.

### List: multiple rules

```yaml
access:
  - moderator
  - given:
      principal: identity:user
      document: posts
    when: principal.sub equals document.authorId
```

Or inline (YAML flow syntax):

```yaml
access: "[user:admin, user:moderator]"
```

Rules in a list are evaluated top-to-bottom. The first matching rule determines the outcome.

## ABAC rules: `given`/`when`/`then`

Attribute-based rules check conditions on the principal and/or a loaded document.

```yaml
access:
  - given:
      principal: identity:user      # bind authenticated user as "principal"
      document: posts               # load document from "posts" repository
    when: principal.sub equals document.authorId
    then: allow                     # default, can be omitted
  - then: deny                      # fallback
```

### `given` fields

| Field | Required | Description |
|-------|----------|-------------|
| `principal` | no | Binds the authenticated principal. Value must be `identity:<entityName>`. |
| `document` | no | Loads the target document. Value is a repository name. |

Both `principal` and `document` are optional, but at least one must be present for a `when:` condition.

### `when`

A string expression (or list of expressions ANDed together) evaluated against the bound values. See [when-expressions overview](../when-expressions/overview.md).

### `then`

`allow` (default) or `deny`. When `then: deny`, the rule denies access if the `when` condition is true.

## Evaluation order

1. Rules are evaluated top-to-bottom.
2. First matching rule wins (allow or deny).
3. If no rule matches, the request is denied (implicit deny).

## Precedence: controller vs operation

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

- 401 Unauthorized: credentials are missing or invalid (not authenticated).
- 403 Forbidden: credentials are valid but the principal doesn't satisfy the access rule (not authorized).
