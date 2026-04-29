---
title: "Custom Service Operations"
description: Custom operations let you attach arbitrary Python handler functions to a service, exposing them as HTTP routes through a controller.
---

Custom operations let you attach arbitrary Python handler functions to a service, exposing them as HTTP routes through a controller.

## Declaration

In the service:

```yaml
services:
  posts:
    operations:
      publish: { handler: blog.publish_post }
      archive: { handler: blog.archive_post }
```

`handler:` is `<importKey>.<functionName>`. The import key must appear in `imports:`:

```yaml
imports:
  blog: myapp.handlers.blog
```

## Exposing via controller

The controller operation references the service operation by name and can set custom `method:` and `path:`:

```yaml
controllers:
  posts:
    service: posts
    base_path: /posts
    operations:
      publish:
        method: POST
        path: "/{id}/publish"
        access: "*"
      archive:
        method: POST
        path: "/{id}/archive"
        access: moderator
```

If `method:` and `path:` are omitted, the engine infers them from the operation name.

## Handler signature

```python
# myapp/handlers/blog.py
async def publish_post(context):
    doc = await context.repository.get(context.params["id"])
    if doc.get("published"):
        raise ValueError("Already published")
    return await context.repository.update(
        context.params["id"],
        {"published": True, "publishedAt": context.now()}
    )

async def archive_post(context):
    return await context.repository.update(
        context.params["id"],
        {"status": "archived"}
    )
```

### `context` object

| Attribute | Description |
|-----------|-------------|
| `context.repository` | Repository instance for the service's bound repository |
| `context.params` | Path and query parameters |
| `context.body` | Parsed request body |
| `context.principal` | Authenticated principal (`sub`, `record`, `roles`) or `None` |
| `context.now()` | Current UTC datetime |

## Return value

Return a dict or list. It is serialized as JSON and sent as the response body. Raise an exception to return an error.

## Access control

Custom operations participate in the same access control system as built-in operations. Specify `access:` on the controller operation exactly as you would for `create`, `update`, etc.
