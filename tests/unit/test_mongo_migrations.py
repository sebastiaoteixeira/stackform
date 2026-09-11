"""Native MongoDB migrations driven through `yaml-api migrate`.

No async-capable Mongo double exists for ``pymongo.AsyncMongoClient`` (mongomock
and mongomock_motor target the synchronous client and Motor), so a fake async
database stands in. It enforces the two server behaviours these migrations lean
on: ``_id`` uniqueness, which is what makes a revision claim atomic, and a
failing ``drop_index`` for an index that is not there. Its cursors and index
builds yield to the event loop, so two upgrades can race deterministically.
"""

import asyncio
import json
import textwrap
from contextlib import asynccontextmanager
from typing import Any
from uuid import uuid4

import pytest
from click.testing import CliRunner
from pymongo.errors import DuplicateKeyError, OperationFailure

from yaml_api_generator.cli import cli
from yaml_api_generator.migrations import alembic_support, mongo_support
from yaml_api_generator.migrations.dispatch import resolve_driver
from yaml_api_generator.migrations.mongo_support import (
    STORE_COLLECTION,
    MigrationError,
    Revision,
    RevisionState,
    load_revisions,
    make_config,
)

HANDLER_CALLS: list[str] = []
NOT_A_HANDLER = "a string is not callable"


async def backfill(db: "FakeDB") -> None:
    HANDLER_CALLS.append("backfill")
    await db["users"].insert_one({"_id": "seed", "email": "seed@example.com"})


async def explode(db: "FakeDB") -> None:
    HANDLER_CALLS.append("explode")
    raise RuntimeError("handler failed halfway")


def _matches(document: dict[str, Any], criteria: dict[str, Any]) -> bool:
    return all(document.get(key) == value for key, value in criteria.items())


class FakeCursor:
    def __init__(self, docs: list[dict[str, Any]]) -> None:
        self._docs = docs

    async def to_list(self, length: int | None = None) -> list[dict[str, Any]]:
        await asyncio.sleep(0)
        return self._docs


class FakeCollection:
    def __init__(self) -> None:
        self.docs: dict[str, dict[str, Any]] = {}
        self.indexes: dict[str, dict[str, Any]] = {"_id_": {}}
        self.created: list[str] = []

    async def create_index(self, keys: Any, name: str | None = None, **kwargs: Any) -> str:
        await asyncio.sleep(0)
        name = name or f"{keys}_1"
        self.indexes[name] = kwargs
        self.created.append(name)
        return name

    async def drop_index(self, name: str) -> None:
        if name not in self.indexes:
            raise OperationFailure(f"index not found with name [{name}]")
        del self.indexes[name]

    def list_indexes(self) -> FakeCursor:
        return FakeCursor([{"name": name} for name in self.indexes])

    async def insert_one(self, document: dict[str, Any]) -> None:
        document = dict(document)
        document.setdefault("_id", uuid4().hex)
        if document["_id"] in self.docs:
            raise DuplicateKeyError(f"E11000 duplicate key: {document['_id']}")
        self.docs[document["_id"]] = document

    async def delete_one(self, criteria: dict[str, Any]) -> None:
        for key, document in self.docs.items():
            if _matches(document, criteria):
                del self.docs[key]
                return

    async def find_one_and_update(
        self, criteria: dict[str, Any], update: dict[str, Any], **kwargs: Any
    ) -> dict[str, Any] | None:
        for document in self.docs.values():
            if _matches(document, criteria):
                document.update(update["$set"])
                return dict(document)
        return None

    def find(self, criteria: dict[str, Any]) -> FakeCursor:
        return FakeCursor(
            [dict(d) for d in self.docs.values() if _matches(d, criteria)]
        )


class FakeDB:
    def __init__(self) -> None:
        self.collections: dict[str, FakeCollection] = {}

    def __getitem__(self, name: str) -> FakeCollection:
        return self.collections.setdefault(name, FakeCollection())

    async def list_collection_names(self) -> list[str]:
        return list(self.collections)


@pytest.fixture(autouse=True)
def _reset_handler_calls():
    HANDLER_CALLS.clear()


def _write_spec(tmp_path) -> Any:
    spec = tmp_path / "spec.yaml"
    spec.write_text(textwrap.dedent("""
        version: "0.2"
        api: { basePath: /api }
        datastores:
          store: { type: mongodb, uri: "mongodb://localhost:27017", database: test, default: true }
        entities:
          user:
            fields:
              id: { type: id }
              email: { type: string, required: true, unique: true }
        repositories: { users: { entity: user } }
        services: { users: { repository: users } }
        controllers:
          users:
            base_path: /users
            routes: { list: { service: users, method: GET, path: "", access: public } }
    """))
    return spec


def _config_on(spec, db: FakeDB) -> mongo_support.MongoMigrationConfig:
    config = make_config(str(spec))

    @asynccontextmanager
    async def connect():
        yield db

    config.connect = connect
    return config


def _collection_name(config) -> str:
    return mongo_support._desired_indexes(config.ir, config.datastore)[0][0]


def _ledger(db: FakeDB) -> dict[str, dict[str, Any]]:
    return db[STORE_COLLECTION].docs


def _handler_revision(
    config, message: str, dotted: str, down_revision: str | None = None
) -> Revision:
    revision = Revision(
        revision=uuid4().hex[:12],
        down_revision=down_revision,
        message=message,
        operations=[{"op": "run_handler", "up": dotted}],
    )
    config.directory.mkdir(parents=True, exist_ok=True)
    mongo_support._write_revision(config.directory, 1, revision)
    return revision


def test_new_autogenerates_index_revision(tmp_path):
    spec = _write_spec(tmp_path)
    config = _config_on(spec, FakeDB())

    mongo_support.new_revision(config, "init")

    revisions = load_revisions(config.directory)
    assert len(revisions) == 1
    assert revisions[0].down_revision is None
    assert revisions[0].operations == [
        {
            "op": "create_index",
            "collection": _collection_name(config),
            "field": "email",
            "unique": True,
        }
    ]


def test_new_generates_unique_ids_after_a_revision_file_is_deleted(tmp_path):
    spec = _write_spec(tmp_path)
    config = _config_on(spec, FakeDB())

    mongo_support.new_revision(config, "init")
    first = load_revisions(config.directory)[0]
    next(config.directory.glob("*.json")).unlink()
    mongo_support.new_revision(config, "init again")

    assert load_revisions(config.directory)[0].revision != first.revision


def test_new_needs_no_database(tmp_path):
    spec = _write_spec(tmp_path)
    config = make_config(str(spec))

    @asynccontextmanager
    async def unreachable():
        raise AssertionError("migrate new must not open a connection")
        yield

    config.connect = unreachable
    mongo_support.new_revision(config, "init")

    assert len(load_revisions(config.directory)) == 1


def test_new_message_cannot_escape_the_migrations_directory(tmp_path):
    spec = _write_spec(tmp_path)
    runner = CliRunner()

    result = runner.invoke(
        cli, ["migrate", "new", str(spec), "-m", "../../../etc/passwd"]
    )

    assert result.exit_code == 0, result.output
    written = list(config_directory(spec).glob("*.json"))
    assert len(written) == 1
    assert written[0].parent == config_directory(spec)
    assert ".." not in written[0].name and "/" not in written[0].name
    assert json.loads(written[0].read_text())["message"] == "../../../etc/passwd"


def config_directory(spec):
    return mongo_support.mongo_migrations_dir(str(spec), "store")


def test_up_applies_index_and_records_history(tmp_path):
    spec = _write_spec(tmp_path)
    db = FakeDB()
    config = _config_on(spec, db)
    coll = _collection_name(config)

    mongo_support.new_revision(config, "init")
    mongo_support.upgrade(config, "head")

    applied = load_revisions(config.directory)[0]
    assert "email_1" in db[coll].indexes
    assert list(_ledger(db)) == [applied.revision]
    assert _ledger(db)[applied.revision]["state"] is RevisionState.APPLIED


def test_up_twice_is_idempotent(tmp_path):
    spec = _write_spec(tmp_path)
    db = FakeDB()
    config = _config_on(spec, db)
    coll = _collection_name(config)

    mongo_support.new_revision(config, "init")
    mongo_support.upgrade(config, "head")
    mongo_support.upgrade(config, "head")

    assert db[coll].created == ["email_1"]
    assert len(_ledger(db)) == 1


def test_concurrent_upgrades_apply_each_revision_once(tmp_path):
    spec = _write_spec(tmp_path)
    db = FakeDB()
    config = _config_on(spec, db)
    coll = _collection_name(config)
    mongo_support.new_revision(config, "init")
    mongo_support.new_revision(config, "second")

    async def race():
        await asyncio.gather(
            mongo_support._upgrade(config, "head"),
            mongo_support._upgrade(config, "head"),
        )

    asyncio.run(race())

    assert db[coll].created == ["email_1"]
    assert len(_ledger(db)) == 2
    assert all(
        doc["state"] is RevisionState.APPLIED for doc in _ledger(db).values()
    )


def test_second_runner_skips_a_claimed_revision_without_side_effects(tmp_path):
    spec = _write_spec(tmp_path)
    db = FakeDB()
    config = _config_on(spec, db)
    revision = _handler_revision(config, "backfill", f"{__name__}.backfill")
    mongo_support.upgrade(config, "head")
    HANDLER_CALLS.clear()

    mongo_support.upgrade(config, "head")

    assert HANDLER_CALLS == []
    assert list(_ledger(db)) == [revision.revision]


def test_interrupted_revision_is_detectable_and_blocks_the_next_run(tmp_path):
    spec = _write_spec(tmp_path)
    db = FakeDB()
    config = _config_on(spec, db)
    revision = _handler_revision(config, "explode", f"{__name__}.explode")

    with pytest.raises(RuntimeError):
        mongo_support.upgrade(config, "head")
    assert _ledger(db)[revision.revision]["state"] is RevisionState.RUNNING

    with pytest.raises(MigrationError, match=revision.revision):
        mongo_support.upgrade(config, "head")
    with pytest.raises(MigrationError, match="forward-only"):
        mongo_support.downgrade(config, "-1")
    assert HANDLER_CALLS == ["explode"]


def test_status_reports_pending_interrupted_and_orphaned_entries(tmp_path, capsys):
    spec = _write_spec(tmp_path)
    db = FakeDB()
    config = _config_on(spec, db)
    mongo_support.new_revision(config, "init")
    mongo_support.upgrade(config, "head")
    mongo_support.new_revision(config, "second")
    applied, pending = load_revisions(config.directory)
    _ledger(db)["ghost"] = {
        "_id": "ghost",
        "message": "gone",
        "state": RevisionState.RUNNING,
    }

    mongo_support.status(config)

    out = capsys.readouterr().out
    assert f"Current revision: {applied.revision}" in out
    assert f"Pending: {pending.revision}" in out
    assert "Interrupted: ghost" in out
    assert "Recorded with no revision file: ghost" in out


def test_history_marks_applied_revisions(tmp_path, capsys):
    spec = _write_spec(tmp_path)
    db = FakeDB()
    config = _config_on(spec, db)
    mongo_support.new_revision(config, "init")
    mongo_support.upgrade(config, "head")
    mongo_support.new_revision(config, "second")
    applied, pending = load_revisions(config.directory)

    mongo_support.history(config)

    out = capsys.readouterr().out
    assert f"(base) -> {applied.revision}: init [applied]" in out
    assert f"{applied.revision} -> {pending.revision}: second [pending]" in out


def test_down_reverses_autogenerated_index(tmp_path):
    spec = _write_spec(tmp_path)
    db = FakeDB()
    config = _config_on(spec, db)
    coll = _collection_name(config)

    mongo_support.new_revision(config, "init")
    mongo_support.upgrade(config, "head")
    mongo_support.downgrade(config, "-1")

    assert "email_1" not in db[coll].indexes
    assert _ledger(db) == {}


def test_down_without_a_down_handler_names_the_revision(tmp_path):
    spec = _write_spec(tmp_path)
    db = FakeDB()
    config = _config_on(spec, db)
    revision = _handler_revision(config, "backfill", f"{__name__}.backfill")
    mongo_support.upgrade(config, "head")

    with pytest.raises(MigrationError, match=f"{revision.revision}.*no 'down' handler"):
        mongo_support.downgrade(config, "-1")


def test_handler_must_be_callable(tmp_path):
    spec = _write_spec(tmp_path)
    config = _config_on(spec, FakeDB())
    revision = _handler_revision(config, "broken", f"{__name__}.NOT_A_HANDLER")

    with pytest.raises(MigrationError, match=f"{revision.revision}.*not a callable"):
        mongo_support.upgrade(config, "head")


def test_data_migration_handler_runs_and_is_recorded(tmp_path):
    spec = _write_spec(tmp_path)
    db = FakeDB()
    config = _config_on(spec, db)
    revision = _handler_revision(config, "backfill", f"{__name__}.backfill")

    mongo_support.upgrade(config, "head")

    assert "seed" in db["users"].docs
    assert list(_ledger(db)) == [revision.revision]


def test_relative_and_explicit_targets(tmp_path):
    spec = _write_spec(tmp_path)
    db = FakeDB()
    config = _config_on(spec, db)
    mongo_support.new_revision(config, "init")
    mongo_support.new_revision(config, "second")
    first, second = load_revisions(config.directory)

    mongo_support.upgrade(config, "+1")
    assert list(_ledger(db)) == [first.revision]

    mongo_support.upgrade(config, second.revision)
    assert list(_ledger(db)) == [first.revision, second.revision]

    mongo_support.downgrade(config, "-1")
    assert list(_ledger(db)) == [first.revision]

    mongo_support.upgrade(config, "head")
    mongo_support.downgrade(config, first.revision)
    assert list(_ledger(db)) == [first.revision]

    mongo_support.downgrade(config, "base")
    assert _ledger(db) == {}


@pytest.mark.parametrize(
    "command, target",
    [("up", "nope"), ("up", "-1"), ("down", "nope"), ("down", "+2")],
)
def test_unrecognised_targets_are_refused(tmp_path, command, target):
    spec = _write_spec(tmp_path)
    db = FakeDB()
    config = _config_on(spec, db)
    mongo_support.new_revision(config, "init")
    mongo_support.upgrade(config, "head")
    before = dict(_ledger(db))

    driver = mongo_support.upgrade if command == "up" else mongo_support.downgrade
    with pytest.raises(MigrationError, match="Unrecognised target"):
        driver(config, target)
    assert _ledger(db) == before


def test_cli_refuses_an_unknown_target_without_connecting(tmp_path):
    spec = _write_spec(tmp_path)
    runner = CliRunner()

    result = runner.invoke(cli, ["migrate", "up", str(spec), "--to", "nope"])

    assert result.exit_code == 1
    assert "Unrecognised target 'nope'" in result.output


def test_baseline_is_stamped_on_up_when_schema_already_present(tmp_path):
    spec = _write_spec(tmp_path)
    db = FakeDB()
    config = _config_on(spec, db)
    db[_collection_name(config)].indexes["email_1"] = {"unique": True}
    revision = _handler_revision(config, "init", f"{__name__}.backfill")

    mongo_support.upgrade(config, "head")

    assert HANDLER_CALLS == []
    assert _ledger(db)[revision.revision]["state"] is RevisionState.APPLIED


def test_baseline_not_stamped_on_empty_datastore(tmp_path):
    spec = _write_spec(tmp_path)
    db = FakeDB()
    config = _config_on(spec, db)
    _handler_revision(config, "init", f"{__name__}.backfill")

    mongo_support.upgrade(config, "head")

    assert HANDLER_CALLS == ["backfill"]


def test_revision_order_follows_the_down_revision_chain(tmp_path):
    spec = _write_spec(tmp_path)
    config = _config_on(spec, FakeDB())
    config.directory.mkdir(parents=True, exist_ok=True)
    mongo_support._write_revision(config.directory, 2, Revision("b", None, "first", []))
    mongo_support._write_revision(config.directory, 1, Revision("a", "b", "second", []))

    assert [r.revision for r in load_revisions(config.directory)] == ["b", "a"]


@pytest.mark.parametrize(
    "revisions, expected",
    [
        ([("a", None), ("c", "missing")], "Broken revision chain"),
        ([("a", None), ("a", "other")], "Duplicate revision id 'a'"),
        ([("a", None), ("b", None)], "Branched history"),
    ],
)
def test_broken_chains_are_refused(tmp_path, revisions, expected):
    spec = _write_spec(tmp_path)
    config = _config_on(spec, FakeDB())
    config.directory.mkdir(parents=True, exist_ok=True)
    for sequence, (revision, down) in enumerate(revisions):
        path = config.directory / f"{sequence:04d}_{revision}_{down}.json"
        path.write_text(
            json.dumps(
                {
                    "revision": revision,
                    "down_revision": down,
                    "message": "x",
                    "operations": [],
                }
            )
        )

    with pytest.raises(MigrationError, match=expected):
        load_revisions(config.directory)


def test_loader_disables_index_creation_when_migrations_present(tmp_path):
    from yaml_api_generator.server.common.loader import create_repositories
    from yaml_api_generator.server.common.repositories import MongoRepository

    spec = _write_spec(tmp_path)
    (tmp_path / "mongo_migrations").mkdir()

    _, registry = create_repositories(str(spec))
    repo = registry.for_collection(_collection_name(make_config(str(spec))))
    assert isinstance(repo, MongoRepository)
    assert repo.manage_indexes is False


def test_resolve_driver_returns_driver_and_parsed_config(tmp_path):
    mongo_spec = _write_spec(tmp_path)
    driver, config = resolve_driver(str(mongo_spec), None)
    assert driver is mongo_support
    assert config.datastore == "store"

    relational = tmp_path / "rel.yaml"
    relational.write_text(textwrap.dedent("""
        version: "0.2"
        api: { basePath: /api }
        datastores:
          store: { type: postgres, dsn: "sqlite:///x.db", default: true }
        entities:
          task: { fields: { id: { type: id }, title: { type: string, required: true } } }
        repositories: { tasks: { entity: task } }
        services: { tasks: { repository: tasks } }
        controllers:
          tasks:
            base_path: /tasks
            routes: { list: { service: tasks, method: GET, path: "", access: public } }
    """))

    driver, config = resolve_driver(str(relational), None)
    assert driver is alembic_support
    assert config.attributes["datastore"] == "store"
