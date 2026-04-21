# Troubleshooting

## MongoDB connection refused

```
ConnectionError: Connection refused on localhost:27017
```

MongoDB is not running. Start it with `docker-compose up -d` or install and start it manually.

## YAML parse error

```
{"code": "YAML_PARSE_ERROR", "message": "...", "path": "...", "hint": "..."}
```

Check your YAML syntax. Common issues: wrong indentation, missing colons, tabs instead of spaces.

## Schema validation error

```
{"code": "SCHEMA_VALIDATION_ERROR", "message": "...", "path": "..."}
```

Your spec is valid YAML but does not match the expected structure. Check the field name and type at the path shown in the error.

## 422 Unprocessable Entity

The request body does not match the expected schema. Check required fields and types. For enum fields, the value must be one of the declared `values`.

## 401 Unauthorized

The endpoint requires authentication. Include a valid JWT token:

```
Authorization: Bearer <token>
```

Get a token by calling the login endpoint (e.g., `POST /users/login`).

## 403 Forbidden

You are authenticated but do not have the required role or permissions. Check the access rules on the controller for that operation.

## Missing environment variable

```
{"code": "INTERPOLATION_MISSING_VAR", "message": "..."}
```

A `${VAR_NAME}` in your spec references an environment variable that is not set. Either set it or use a default value: `${VAR_NAME:-default}`.

## JWT_SECRET warning

In production, always set the `JWT_SECRET` environment variable to a strong random value. The default is insecure and only suitable for development.

```bash
export JWT_SECRET=$(openssl rand -hex 32)
yaml-api dev myapp.yaml
```
