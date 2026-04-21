---
title: "Reference: `mongo:`"
description: The `mongo:` section configures the MongoDB connection.
---

# Reference: `mongo:`

The `mongo:` section configures the MongoDB connection.

## Schema

```yaml
mongo:
  uri: mongodb://localhost:27017
  database: myapp
```

## Fields

### `uri`

Type: string. Required.

Full MongoDB connection string. Supports all standard MongoDB URI options (auth, replica sets, TLS, etc.).

```yaml
# Local
uri: mongodb://localhost:27017

# With credentials
uri: mongodb://user:password@host:27017

# Atlas
uri: mongodb+srv://user:password@cluster.mongodb.net

# Replica set
uri: mongodb://host1:27017,host2:27017/?replicaSet=rs0
```

Always use `${VAR}` interpolation for credentials:

```yaml
uri: ${MONGO_URI}
# or with fallback for local dev:
uri: ${MONGO_URI:-mongodb://localhost:27017}
```

### `database`

Type: string. Required.

Name of the MongoDB database to use. All collections are created in this database.

```yaml
database: myapp
database: ${MONGO_DB:-myapp}
```

## Example

```yaml
mongo:
  uri: ${MONGO_URI:-mongodb://localhost:27017}
  database: ${MONGO_DB:-myapp}
```
