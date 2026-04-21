---
title: "Tutorial 10: External Auth Providers"
description: Adding Google OIDC as an auth provider alongside password login.
---

**Concept introduced:** Adding Google OIDC as an auth provider alongside password login.

## Adding Google OIDC to the user entity

Auth entities support multiple `via:` bindings. Users can log in with password or Google.

```yaml
version: "0.2"

mongo:
  uri: mongodb://localhost:27017
  database: myapp

providers:
  google:
    type: oidc
    client_id: ${GOOGLE_CLIENT_ID}
    client_secret: ${GOOGLE_CLIENT_SECRET}

entities:
  base:
    abstract: true
    fields:
      id: { type: id }
      createdAt: { type: datetime }

  user:
    extends: base
    type: auth
    auth:
      identifier: email
      via: [password, google]
      claim_mapping:
        email: email
        displayName: name
      auto_provision: true
    roles:
      values: [admin, moderator, user]
      default: user
      hierarchy:
        admin: [moderator]
        moderator: [user]
    fields:
      email: { type: string, required: true, unique: true }
      displayName: { type: string, required: true }

  note:
    extends: base
    fields:
      title: { type: string, required: true }
      body: { type: string }
      authorId: { type: ref, ref: user }
      published: { type: boolean, default: false }

repositories:
  users:
    entity: user
  notes:
    entity: note

services:
  users: {}
  notes:
    operations:
      publish: { handler: notes.publish }

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
      publish:
        method: POST
        path: "/{id}/publish"
        access:
          - given:
              principal: identity:user
              document: notes
            when: principal.sub equals document.authorId
```

## Generated OIDC routes

The engine generates the standard OIDC flow endpoints automatically:

| Method | Path | Description |
|--------|------|-------------|
| GET | /users/auth/google | Redirect to Google's authorization endpoint |
| GET | /users/auth/google/callback | Handle the OAuth2 callback, issue JWT |

## Provider config options

```yaml
providers:
  google:
    type: oidc
    client_id: ${GOOGLE_CLIENT_ID}
    client_secret: ${GOOGLE_CLIENT_SECRET}
    # Discovery URL is inferred for well-known providers:
    # google, microsoft, apple
```

For custom OIDC providers, supply `discovery_url:` explicitly:

```yaml
providers:
  myoidc:
    type: oidc
    client_id: ${CLIENT_ID}
    client_secret: ${CLIENT_SECRET}
    discovery_url: https://auth.example.com/.well-known/openid-configuration
```

## External provider options in the `auth:` block

```yaml
auth:
  identifier: email          # which field to use as the user identifier
  via: [password, google]    # list of auth methods; "google" references providers.google
  claim_mapping:             # map OIDC claims to entity fields
    email: email             # entity_field: oidc_claim
    displayName: name
  auto_provision: true       # create user record on first login if not found
```

- `claim_mapping` is optional. Fields with the same name are mapped automatically.
- `auto_provision: true` means the first Google login creates a user record automatically.
- Without `auto_provision`, the user must already exist (matched by `identifier`) to log in via OIDC.

**Note:** Testing OIDC locally requires a real OAuth app registered with the provider. For Google, create one at https://console.cloud.google.com/apis/credentials and set the redirect URI to `http://localhost:8000/api/v1/users/auth/google/callback`.

## Environment variables

Provider secrets should always use `${VAR}` interpolation. Never hardcode credentials:

```bash
export GOOGLE_CLIENT_ID=your-client-id
export GOOGLE_CLIENT_SECRET=your-client-secret
yaml-api dev myapp.yaml
```

**Watch out:** If `auto_provision: true` and the provider returns claims that do not satisfy the entity's `required` fields, the auto-provisioned user may be created with missing data. Ensure `claim_mapping` covers all required fields, or set sensible defaults on them.

## Key points

- The top-level `providers:` section defines external OIDC/SAML providers.
- `via:` on an auth entity can list multiple bindings. Each generates its own login flow.
- Well-known provider names (`google`, `microsoft`, `apple`) use built-in discovery URLs.
- All auth methods produce the same JWT format -- downstream access rules work identically.

