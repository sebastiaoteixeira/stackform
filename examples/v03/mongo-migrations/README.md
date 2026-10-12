# MongoDB migration example

Start MongoDB, then create and apply the first native revision:

```bash
stackform migrate new examples/v03/mongo-migrations/spec.yaml --message baseline
stackform migrate history examples/v03/mongo-migrations/spec.yaml
stackform migrate up examples/v03/mongo-migrations/spec.yaml
stackform migrate status examples/v03/mongo-migrations/spec.yaml
```

The first `up` safely stamps a schema that already has the declared unique
index. Later revisions apply index changes and record them in the migration
ledger. To reverse all applied revisions:

```bash
stackform migrate down examples/v03/mongo-migrations/spec.yaml --to base
```

After creating `mongo_migrations/`, regenerate deployed backends so index
ownership moves from application startup to the migration lifecycle.
