---
title: "Reference: Services Overview"
description: Services are the business logic layer. Controllers reference services; services reference repositories. Controllers never reference repositories directly.
---

# Reference: Services Overview

Services are the business logic layer. Controllers reference services; services reference repositories. Controllers never reference repositories directly.

## Structure

```yaml
services:
  serviceName:
    # Option 1: delegate to a repository operation
    repository: repositoryName
    operation: operationName

    # Option 2: custom handler
    handler: importKey.functionName

    # Option 3: shorthand empty map (all default operations)
    {}
```

## Shorthand `{}`

An empty map wires up all default operations from the service's namesake repository:

```yaml
services:
  posts: {}
```

This is equivalent to manually declaring `list`, `get`, `create`, `update`, and `delete` services for the `posts` repository, using the global operation defaults.

The service key must match a repository key of the same name for this shorthand to work.

## Delegation to repository operation

```yaml
services:
  list-posts:  { repository: posts, operation: list }
  get-post:    { repository: posts, operation: get }
  create-post: { repository: posts, operation: create }
```

Maps a service name to a specific repository + operation combination. Useful when you need distinct names for controller routes.

## Custom handler

```yaml
services:
  posts:
    operations:
      publish: { handler: blog.publish_post }
```

`handler:` references a Python function via `importKey.functionName`. The import key must be declared in the top-level `imports:` section.

```yaml
imports:
  blog: myapp.handlers.blog
```

## Auth service operations

Auth entities implicitly have `register` and `login` service operations when `api.operations.auth` is enabled. These can be exposed on controller operations:

```yaml
controllers:
  users:
    service: users
    base_path: /users
    operations:
      register: { access: public }
      login: { access: public }
```

## Example

```yaml
imports:
  blog: myapp.handlers.blog

services:
  users: {}

  posts:
    operations:
      publish: { handler: blog.publish_post }

  # Explicit delegation
  list-posts:   { repository: posts, operation: list }
  create-post:  { repository: posts, operation: create }
```
