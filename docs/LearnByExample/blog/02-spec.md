# Blog App: Full Spec

```yaml
version: "0.2"

mongo:
  uri: ${MONGO_URI:-mongodb://localhost:27017}
  database: ${MONGO_DB:-blog}

# Abstract base provides id and createdAt to all entities
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
      via: password
    roles:
      values: [admin, moderator, user]
      default: user
      hierarchy:
        admin: [moderator]
        moderator: [user]
    fields:
      email: { type: string, required: true, unique: true }
      displayName: { type: string, required: true }

  post:
    extends: base
    fields:
      title: { type: string, required: true }
      content: { type: string }
      authorId: { type: ref, ref: user }
      published: { type: boolean, default: false }
      publishedAt: { type: datetime }
      tags:
        type: array
        items:
          type: string

  # Natural key: country code is the primary key, no auto-generated id
  country:
    pk: code
    fields:
      code: { type: string }
      name: { type: string, required: true }

repositories:
  users:
    entity: user
  posts:
    entity: post
    operations:
      replace: true
  countries:
    entity: country

services:
  users: {}
  posts:
    operations:
      publish: { handler: blog.publish_post }
  countries: {}

controllers:
  users:
    service: users
    base_path: /users
    access: "*"
    operations:
      register: { access: public }
      login: { access: public }
      delete:
        access:
          - admin
          - given:
              principal: identity:user
              document: users
            when: principal.sub equals document.id

  posts:
    service: posts
    base_path: /posts
    access: public
    operations:
      create: { access: "*" }
      update:
        access:
          - moderator
          - given:
              principal: identity:user
              document: posts
            when: principal.sub equals document.authorId
      replace:
        access:
          - moderator
          - given:
              principal: identity:user
              document: posts
            when: principal.sub equals document.authorId
      delete:
        access:
          - moderator
          - given:
              principal: identity:user
              document: posts
            when: principal.sub equals document.authorId
      publish:
        method: POST
        path: "/{id}/publish"
        access:
          - moderator
          - given:
              principal: identity:user
              document: posts
            when: principal.sub equals document.authorId

  countries:
    service: countries
    base_path: /countries
    access: public
    operations:
      create: { access: admin }
      update: { access: admin }
      delete: { access: admin }
```
