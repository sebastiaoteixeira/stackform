# Tutorial 07: ABAC Rules

**Concept introduced:** Attribute-based access control using `given`/`when`/`then` -- document-level rules.

## Authors can edit their own notes

Role-based rules (`admin`, `moderator`) cover broad access. ABAC rules cover ownership and record-level conditions.

```yaml
version: "0.2"

mongo:
  uri: mongodb://localhost:27017
  database: myapp

entities:
  user:
    type: auth
    auth:
      identifier: email
      via: password
    roles:
      values: [admin, moderator, user]
      default: user
      hierarchy:
        admin: [moderator]
        moderator: [user]
    fields:
      id: { type: id }
      email: { type: string, required: true, unique: true }
      displayName: { type: string, required: true }

  note:
    fields:
      id: { type: id }
      title: { type: string, required: true }
      body: { type: string }
      authorId: { type: ref, ref: user }

repositories:
  users:
    entity: user
  notes:
    entity: note

services:
  users: {}
  notes: {}

controllers:
  users:
    service: users
    base_path: /users
    operations:
      register: { access: public }
      login: { access: public }

  notes:
    service: notes
    base_path: /notes
    access: public
    operations:
      create: { access: "*" }
      update:
        access:
          - moderator
          - given:
              principal: identity:user
              document: notes
            when: principal.sub equals document.authorId
      delete:
        access:
          - moderator
          - given:
              principal: identity:user
              document: notes
            when: principal.sub equals document.authorId
```

## How given/when/then works

Each item in the `access:` list is evaluated top-to-bottom. The first matching rule wins.

```yaml
access:
  - moderator                           # rule 1: allow moderators (and above)
  - given:
      principal: identity:user          # bind the authenticated user as "principal"
      document: notes                   # load the target document as "document"
    when: principal.sub equals document.authorId   # condition
    # then: allow                       # default when omitted
```

- `then: allow` is the default. You can write `then: deny` to invert the logic.
- If no rule matches, the request is denied.

## Deny pattern: block non-authors from updating

```yaml
update:
  access:
    - admin
    - given:
        principal: identity:user
        document: notes
      when: principal.sub not equals document.authorId
      then: deny
    - then: allow
```

Rule sequence: admin passes first. Non-authors are denied. Everyone else (the author) reaches the final `then: allow`.

## When expression syntax

```yaml
when: principal.sub equals document.authorId
when: principal.record.role equals 'admin'
when: principal.record.role in ['admin', 'moderator']
when: document.status not in ['deleted', 'archived']
```

- `principal.sub` -- the principal's unique identifier (primary key value)
- `principal.record.fieldName` -- any field on the authenticated user's record
- `document.fieldName` -- any field on the document being accessed

**Note:** On `create` operations, there is no existing document yet. Rules with `document:` bindings are skipped for create. Use principal-only rules (like role checks) to control create access.

## Key points

- Rules are evaluated in order. Put broad role rules first, document-specific rules after.
- `document:` in `given:` references the repository name (`notes`), not the entity name.
- `then: deny` combined with a fallback `then: allow` is a common pattern for inverse logic.
