"""Graduation from create-on-connect is decided per datastore family.

A polyglot spec declares one relational and one MongoDB datastore whose DSN and
URI are never contacted, since both repositories connect lazily. The generated
FastAPI backend is compiled and its lifespan executed against stub dependencies,
so the startup path is exercised rather than pattern-matched.
"""

import compileall
import sys
import textwrap
import types
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import APIRouter

from yaml_api_generator.cli.compiler import compile_project
from yaml_api_generator.parsers.yaml_parser import ConfigErrors
from yaml_api_generator.server.common.loader import SchemaManagement, create_repositories
from yaml_api_generator.server.common.repositories import MongoRepository
from yaml_api_generator.server.common.repositories.sql import SQLRepository
from yaml_api_generator.runtime import lifecycle


_SPEC = """
    version: "0.2"
    api: { basePath: /api }
    datastores:
      warehouse: { type: postgres, dsn: "sqlite+aiosqlite:///warehouse.db", default: true }
      documents: { type: mongodb, uri: "mongodb://localhost:27017", database: docs }
    entities:
      task: { fields: { id: { type: id }, title: { type: string, required: true } } }
      note: { fields: { id: { type: id }, slug: { type: string, unique: true } } }
    repositories:
      tasks: { entity: task }
      notes: { entity: note, datastore: documents }
    services:
      tasks: { repository: tasks }
      notes: { repository: notes }
    controllers:
      tasks:
        base_path: /tasks
        routes: { list: { service: tasks, method: GET, path: "", access: public } }
      notes:
        base_path: /notes
        routes: { list: { service: notes, method: GET, path: "", access: public } }
"""

_MONGO_SPEC = """
    version: "0.3"
    api: { basePath: /api }
    datastores:
      documents:
        type: mongodb
        uri: "mongodb://db.example:27018"
        database: generated_audit
        default: true
    entities:
      note: { fields: { id: { type: id }, slug: { type: string, unique: true } } }
    repositories:
      notes: { entity: note, datastore: documents }
    services:
      notes: { repository: notes }
    controllers:
      notes:
        base_path: /notes
        routes: { list: { service: notes, method: GET, path: "", access: public } }
"""


def _write_spec(directory: Path, *migration_trees: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    spec = directory / "spec.yaml"
    spec.write_text(textwrap.dedent(_SPEC))
    for tree in migration_trees:
        (directory / tree).mkdir()
    return spec


def _write_mongo_spec(directory: Path, *migration_trees: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    spec = directory / "spec.yaml"
    spec.write_text(textwrap.dedent(_MONGO_SPEC))
    for tree in migration_trees:
        (directory / tree).mkdir()
    return spec


def _repositories(spec: Path) -> tuple[MongoRepository, SQLRepository]:
    _, registry = create_repositories(str(spec))
    mongo, sql = registry.for_collection("notes"), registry.for_collection("tasks")
    assert isinstance(mongo, MongoRepository) and isinstance(sql, SQLRepository)
    return mongo, sql


class TestPerFamilyGraduation:
    def test_alembic_tree_alone_keeps_mongo_indexes_enabled(self, tmp_path):
        mongo, sql = _repositories(_write_spec(tmp_path, "migrations"))
        assert mongo.manage_indexes is True
        assert sql._create_schema is False

    def test_mongo_tree_alone_keeps_sql_create_all_enabled(self, tmp_path):
        mongo, sql = _repositories(_write_spec(tmp_path, "mongo_migrations"))
        assert mongo.manage_indexes is False
        assert sql._create_schema is True

    def test_both_trees_graduate_both_families(self, tmp_path):
        mongo, sql = _repositories(_write_spec(tmp_path, "migrations", "mongo_migrations"))
        assert mongo.manage_indexes is False
        assert sql._create_schema is False

    def test_neither_tree_creates_schema_on_connect(self, tmp_path):
        mongo, sql = _repositories(_write_spec(tmp_path))
        assert mongo.manage_indexes is True
        assert sql._create_schema is True

    def test_only_a_directory_counts_as_a_migrations_tree(self, tmp_path):
        spec = _write_spec(tmp_path)
        (tmp_path / "mongo_migrations").write_text("not a tree")
        assert SchemaManagement.for_spec(spec) == SchemaManagement()


class _NotFound(Exception):
    pass


class _Invalid(Exception):
    pass


class _Conflict(Exception):
    pass


async def _noop() -> None:
    return None


def _stub(name: str, **attributes) -> types.ModuleType:
    module = types.ModuleType(name)
    module.__dict__.update(attributes)
    return module


def _generated_app_dependencies(initialize_indexes) -> dict[str, types.ModuleType]:
    """Inert stand-ins for the sibling modules the generated app imports."""
    return {
        "dependencies": _stub("dependencies"),
        "dependencies.mongodb": _stub(
            "dependencies.mongodb",
            connect_db=lambda: None,
            close_db=_noop,
            initialize_indexes=initialize_indexes,
        ),
        "dependencies.postgres": _stub(
            "dependencies.postgres", connect_db=_noop, close_db=_noop
        ),
        "dependencies.lifecycle": lifecycle,
        "dependencies.repositories": _stub(
            "dependencies.repositories", expiring_repositories=lambda: []
        ),
        "conflicts": _stub("conflicts", ConflictError=_Conflict),
        "services": _stub("services"),
        "services.exceptions": _stub(
            "services.exceptions", NotFoundError=_NotFound, ValidationError=_Invalid
        ),
        "settings": _stub("settings", settings=SimpleNamespace(PORT=8000)),
        "routes": _stub("routes", api_router=APIRouter()),
    }


async def _indexes_created_at_startup(
    project_dir: Path, *migration_trees: str
) -> list[dict[str, list[str]]]:
    created: list[dict[str, list[str]]] = []

    async def initialize_indexes(unique_indexes):
        created.append(unique_indexes)

    spec = _write_spec(project_dir, *migration_trees)
    compile_project(yaml_file=str(spec), output_dir=str(project_dir), target="fastapi")
    backend = project_dir / "backend"
    assert compileall.compile_dir(str(backend), quiet=2), "generated backend must compile"

    module = types.ModuleType("generated_app")
    with patch.dict(sys.modules, _generated_app_dependencies(initialize_indexes)):
        exec(compile((backend / "app.py").read_text(), "app.py", "exec"), module.__dict__)
        async with module.lifespan(module.app):
            pass
    return created


class TestGeneratedFastAPIStartup:
    @pytest.mark.asyncio
    async def test_creates_indexes_when_not_graduated(self, tmp_path):
        assert await _indexes_created_at_startup(tmp_path) == [{"notes": ["slug"]}]

    @pytest.mark.asyncio
    async def test_creates_indexes_under_an_alembic_tree_alone(self, tmp_path):
        created = await _indexes_created_at_startup(tmp_path, "migrations")
        assert created == [{"notes": ["slug"]}]

    @pytest.mark.asyncio
    async def test_skips_indexes_when_graduated(self, tmp_path):
        assert await _indexes_created_at_startup(tmp_path, "mongo_migrations") == []
        assert "initialize_indexes" not in (tmp_path / "backend" / "app.py").read_text()


@pytest.mark.parametrize(
    ("target", "startup_file"),
    [("drf", "api/apps.py"), ("raw", "app.py")],
)
def test_generated_mongo_targets_initialize_indexes_before_graduation(
    tmp_path, target, startup_file
):
    spec = _write_mongo_spec(tmp_path)
    compile_project(yaml_file=str(spec), output_dir=str(tmp_path), target=target)

    source = (tmp_path / "backend" / startup_file).read_text()
    assert "initialize_indexes" in source
    assert '{"notes": ["slug"]}' in source
    assert compileall.compile_dir(str(tmp_path / "backend"), quiet=2)


def test_generated_drf_views_package_does_not_import_absent_route_classes(tmp_path):
    spec = _write_mongo_spec(tmp_path)
    compile_project(yaml_file=str(spec), output_dir=str(tmp_path), target="drf")

    assert (tmp_path / "backend" / "api" / "views" / "__init__.py").read_text() == ""


@pytest.mark.parametrize(
    ("target", "startup_file"),
    [("drf", "api/apps.py"), ("raw", "app.py")],
)
def test_generated_mongo_targets_skip_indexes_after_graduation(
    tmp_path, target, startup_file
):
    spec = _write_mongo_spec(tmp_path, "mongo_migrations")
    compile_project(yaml_file=str(spec), output_dir=str(tmp_path), target=target)

    source = (tmp_path / "backend" / startup_file).read_text()
    assert "initialize_indexes" not in source
    assert compileall.compile_dir(str(tmp_path / "backend"), quiet=2)


def test_generated_fastapi_skips_create_all_after_sql_graduation(tmp_path):
    spec = _write_spec(tmp_path, "migrations")
    compile_project(yaml_file=str(spec), output_dir=str(tmp_path), target="fastapi")

    postgres = (tmp_path / "backend" / "dependencies" / "postgres.py").read_text()
    assert "metadata.create_all" not in postgres
    assert compileall.compile_dir(str(tmp_path / "backend"), quiet=2)


def test_generated_fastapi_creates_sql_schema_before_graduation(tmp_path):
    spec = _write_spec(tmp_path)
    compile_project(yaml_file=str(spec), output_dir=str(tmp_path), target="fastapi")

    postgres = (tmp_path / "backend" / "dependencies" / "postgres.py").read_text()
    assert "metadata.create_all" in postgres


@pytest.mark.parametrize(
    ("target", "settings_file"),
    [("fastapi", "settings.py"), ("drf", "api/settings.py"), ("raw", "settings.py")],
)
def test_generated_mongo_settings_preserve_spec_connection(
    tmp_path, target, settings_file
):
    spec = _write_mongo_spec(tmp_path)
    compile_project(yaml_file=str(spec), output_dir=str(tmp_path), target=target)

    source = (tmp_path / "backend" / settings_file).read_text()
    assert "mongodb://db.example:27018" in source
    assert "generated_audit" in source


@pytest.mark.parametrize("target", ["drf", "raw"])
def test_mongo_only_targets_reject_sql_datastores(tmp_path, target):
    spec = _write_spec(tmp_path)

    with pytest.raises(ConfigErrors) as exc_info:
        compile_project(yaml_file=str(spec), output_dir=str(tmp_path), target=target)

    assert {error.code for error in exc_info.value.errors} == {
        "BACKEND_DATASTORE_UNSUPPORTED"
    }


def test_generated_backend_rejects_multiple_mongo_datastores(tmp_path):
    spec = _write_mongo_spec(tmp_path)
    source = spec.read_text().replace(
        "entities:",
        "  archive: { type: mongodb, uri: 'mongodb://archive:27017', database: archive }\nentities:",
    )
    spec.write_text(source)

    with pytest.raises(ConfigErrors) as exc_info:
        compile_project(yaml_file=str(spec), output_dir=str(tmp_path), target="fastapi")

    assert {error.code for error in exc_info.value.errors} == {
        "BACKEND_DATASTORE_LAYOUT_UNSUPPORTED"
    }
