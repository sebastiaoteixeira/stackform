"""Where a spec keeps its records: the top-level spec block of each kind of datastore and the variables it reads."""

from abc import ABC, abstractmethod
from pathlib import Path
from uuid import uuid4

import pytest


class Datastore(ABC):
    name: str
    spec: str

    @abstractmethod
    def env(self, request: pytest.FixtureRequest, workdir: Path) -> dict[str, str]:
        """The variables ``spec`` reads, holding records no other app shares."""


class SQLDatastore(Datastore):
    name = "sql"
    spec = "datastores:\n  default:\n    type: postgres\n    dsn: ${DATABASE_URL}\n"

    def env(self, request, workdir):
        return {"DATABASE_URL": f"sqlite+aiosqlite:///{workdir / 'records.sqlite'}"}


class MongoDatastore(Datastore):
    name = "mongo"
    spec = "mongo:\n  uri: ${MONGO_URI}\n  database: ${MONGO_DB}\n"

    def env(self, request, workdir):
        return {"MONGO_URI": request.getfixturevalue("mongo_uri"), "MONGO_DB": f"app_{uuid4().hex[:12]}"}


DATASTORES = (SQLDatastore(), MongoDatastore())
