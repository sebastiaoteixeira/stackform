"""Select the migration driver for a spec's chosen datastore.

Both drivers expose the same ``make_config`` / ``new_revision`` / ``upgrade`` /
``downgrade`` / ``status`` / ``history`` surface, so the ``migrate`` CLI dispatches
on datastore kind without forking a parallel command tree. Relational datastores
keep their existing Alembic default: whenever a relational datastore is present
and none is named explicitly, the Alembic driver is chosen exactly as before.
"""

from types import ModuleType

from yaml_api_generator.ir import IRMongo, IRPostgres
from yaml_api_generator.parsers.yaml_parser import load_and_generate_ir

from . import alembic_support, mongo_support


def resolve_driver(spec_path: str, datastore: str | None) -> ModuleType:
    datastores = load_and_generate_ir(spec_path).ir.datastores
    if datastore is not None:
        target = datastores.get(datastore)
        if target is None:
            raise ValueError(f"Unknown datastore '{datastore}'")
        return mongo_support if isinstance(target, IRMongo) else alembic_support
    if any(isinstance(ds, IRPostgres) for ds in datastores.values()):
        return alembic_support
    mongos = [name for name, ds in datastores.items() if isinstance(ds, IRMongo)]
    if len(mongos) == 1:
        return mongo_support
    if not mongos:
        raise ValueError("No datastore declared in this spec")
    raise ValueError("Multiple MongoDB datastores; pass --datastore to choose one")
