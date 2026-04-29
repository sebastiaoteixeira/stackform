---
title: "Access Rules Walkthrough"
---

## Design goals

1. Public read -- anyone can browse posts and countries without logging in.
2. Authenticated write -- any logged-in user can create posts.
3. Author ownership -- users can edit and delete their own posts.
4. Moderation -- moderators can edit or delete any post, regardless of ownership.
5. Admin escalation -- admins inherit all moderator permissions.
6. Self-management -- users can delete their own accounts. Admins can delete any account.

## Rule-by-rule breakdown

### POST /posts (create)

```yaml
create: { access: "*" }
```

Any authenticated user. No role requirement. Anonymous users get 401.

### PATCH /posts/{id} (update)

```yaml
update:
  access:
    - moderator
    - given:
        principal: identity:user
        document: posts
      when: principal.sub equals document.authorId
```

Rule 1: `moderator` -- any user with role `moderator` or `admin` (via hierarchy) passes.
Rule 2: if the authenticated user's `sub` matches the post's `authorId`, allow.
If neither rule matches, deny.

### DELETE /users/{id}

```yaml
delete:
  access:
    - admin
    - given:
        principal: identity:user
        document: users
      when: principal.sub equals document.id
```

Rule 1: `admin` role -- admins can delete any user.
Rule 2: a user can delete their own account (sub equals the user document's id).

### POST /posts/{id}/publish (custom operation)

```yaml
publish:
  method: POST
  path: "/{id}/publish"
  access:
    - moderator
    - given:
        principal: identity:user
        document: posts
      when: principal.sub equals document.authorId
```

Same pattern as update and delete: moderators or the owning author.

### Countries (admin only writes)

```yaml
create: { access: admin }
update: { access: admin }
delete: { access: admin }
```

Reads are `public` (inherited from controller-level `access: public`). Writes require `admin`. Since `admin` includes `moderator` which includes `user`, only explicit `admin` role is accepted here -- `moderator` does not satisfy `access: admin`.

## Role hierarchy in practice

```yaml
roles:
  values: [admin, moderator, user]
  default: user
  hierarchy:
    admin: [moderator]
    moderator: [user]
```

`access: moderator` matches users with role `moderator` or `admin`.
`access: admin` matches only users with role `admin`.
`access: user` matches users with any of the three roles.
`access: "*"` matches any authenticated principal regardless of role.

## ABAC evaluation order

Rules in an `access:` list are evaluated top-to-bottom. The first matching rule wins.

For the posts update rule:
1. Is the principal a moderator or admin? -- allow
2. Does `principal.sub` equal `document.authorId`? -- allow
3. No rule matched -- deny (implicit)

Put the cheapest checks (role-based, no DB lookup) first. Document-level rules require loading the record, so place them later.
