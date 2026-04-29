---
title: Troubleshooting
---

## MongoDB connection refused

```text
ConnectionError: Connection refused on localhost:27017
```

MongoDB is not running. Start it with `docker-compose up -d` or install and start it manually.

## YAML parse error

```json
{"code": "YAML_PARSE_ERROR", "message": "...", "path": "...", "hint": "..."}
```

Check your YAML syntax. Common issues: wrong indentation, missing colons, tabs instead of spaces.

## Schema validation error

```json
{"code": "SCHEMA_VALIDATION_ERROR", "message": "...", "path": "..."}
```

Your spec is valid YAML but does not match the expected structure. Check the field name and type at the path shown in the error.

## 422 Unprocessable Entity

The request body does not match the expected schema. Check required fields and types. For enum fields, the value must be one of the declared `values`.

Example bad request (missing a required `title` field):

```bash
curl -X POST http://localhost:8000/api/v1/notes \
  -H 'Content-Type: application/json' \
  -d '{"body": "Hello"}'
```

Example error response:

```json
{
  "detail": [
    {
      "type": "missing",
      "loc": ["body", "title"],
      "msg": "Field required",
      "input": {"body": "Hello"}
    }
  ]
}
```

The `detail[].loc` array tells you where the problem is. In this case, `["body", "title"]` means the `title` field is missing from the request body. Fix the request by including all required fields.

## 401 Unauthorized

The endpoint requires authentication. Include a valid JWT token:

```text
Authorization: Bearer <token>
```

Get a token by calling the login endpoint (e.g., `POST /users/login`).

## 403 Forbidden

You are authenticated but do not have the required role or permissions. Check the access rules on the controller for that operation.

## Missing environment variable

```json
{"code": "INTERPOLATION_MISSING_VAR", "message": "..."}
```

A `${VAR_NAME}` in your spec references an environment variable that is not set. Either set it or use a default value: `${VAR_NAME:-default}`.

## JWT_SECRET warning

In production, always set the `JWT_SECRET` environment variable to a strong random value. The default is insecure and only suitable for development.

```bash
export JWT_SECRET=$(openssl rand -hex 32)
yaml-api dev myapp.yaml
```
