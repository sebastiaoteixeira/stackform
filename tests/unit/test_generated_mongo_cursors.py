"""Generated Mongo repositories follow pymongo's native async cursor semantics.

``AsyncCollection.aggregate`` is a coroutine that resolves to a cursor, unlike
``find`` which returns the cursor directly. Each backend's generated repository
is imported in a subprocess and run against a collection with those semantics.
"""

import subprocess
import sys
import textwrap

import pytest

from yaml_api_generator.generators.backend.context_builder import build_context
from yaml_api_generator.generators.backend.drf.generator import DRFGenerator
from yaml_api_generator.generators.backend.fastapi.generator import FastAPIGenerator
from yaml_api_generator.generators.backend.raw.generator import RawASGIGenerator
from yaml_api_generator.parsers.yaml_parser import load_and_generate_ir

_SPEC = """
    version: "0.3"
    api: { basePath: "" }
    mongo: { uri: "mongodb://localhost:27017", database: testdb }
    entities:
      member:
        fields:
          id: { type: id, format: uuidv4 }
          email: { type: string, required: true }
    repositories:
      members:
        entity: member
        operations:
          summarize:
            query:
              command: aggregate
              pipeline: [{ $count: total }]
    services:
      members: { repository: members }
    controllers:
      members:
        base_path: /members
        routes:
          create: { service: members, method: POST, path: "", access: public }
"""

_VERIFY = """
    import asyncio
    import importlib

    repository_module = importlib.import_module({repository_module!r})

    class Cursor:
        async def to_list(self, length=None):
            return [{{"total": 1}}]

    class Collection:
        async def aggregate(self, pipeline):
            return Cursor()

    repository = repository_module.MembersRepository({{"members": Collection()}})
    assert asyncio.run(repository.summarize([{{"$count": "total"}}])) == [{{"total": 1}}]
"""


@pytest.mark.parametrize(
    ("generator", "repository_module"),
    [
        (FastAPIGenerator(), "repositories.members"),
        (DRFGenerator(), "api.repositories.members"),
        (RawASGIGenerator(), "repositories.members"),
    ],
)
def test_generated_aggregate_awaits_driver_cursor(generator, repository_module, tmp_path):
    spec = tmp_path / "spec.yaml"
    spec.write_text(textwrap.dedent(_SPEC))
    output = tmp_path / generator.__class__.__name__
    generator.generate(build_context(load_and_generate_ir(str(spec)).ir), output)
    result = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(_VERIFY).format(repository_module=repository_module)],
        cwd=output,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
