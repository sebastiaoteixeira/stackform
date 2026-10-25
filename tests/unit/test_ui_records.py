"""The generated UI reaches the API through the routes, pagination, roles, access and projections the spec declares."""

import json
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest

from yaml_api_generator.cli.compiler import compile_project
from yaml_api_generator.generators.frontend.packs.loader import load_pack
from yaml_api_generator.generators.frontend.renderer import render_templates
from yaml_api_generator.parsers.ui_parser import build_generator_context
from yaml_api_generator.parsers.yaml_parser import load_and_generate_ir
from yaml_api_generator.server.factory import RAW_ENV, SPEC_ENV

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"

SPEC = """
version: "0.3"

api:
  basePath: /api
  version: v1
  operations:
    defaults: { list: true, get: true, create: true, update: true, replace: false, delete: true }
    auth: { register: true, login: true }

datastores:
  local: { type: postgres, dsn: "sqlite+aiosqlite:///records.sqlite", default: true }

entities:
  member:
    type: auth
    auth: { identifier: handle, via: password }
    roles:
      values: [owner, viewer]
      default: viewer
      hierarchy: { owner: [viewer] }
    fields:
      id: { type: id }
      handle: { type: string, required: true, unique: true }
      age: { type: number }
      active: { type: boolean, default: true }
  ledger:
    fields: &rows
      id: { type: id }
      code: { type: string, required: true, unique: true }
      rank: { type: number, required: true }
  page:
    fields: *rows
  feed:
    fields: *rows
  stream:
    fields: *rows
  note:
    fields:
      id: { type: id }
      body: { type: string, required: true }
      entry: { type: ref, ref: ledger }
      signer: { type: ref, ref: member }

repositories:
  members: { entity: member }
  ledgers: { entity: ledger }
  pages: { entity: page }
  feeds: { entity: feed }
  streams: { entity: stream }
  notes: { entity: note }

services:
  members: { repository: members }
  ledgers: { repository: ledgers }
  pages: { repository: pages }
  feeds: { repository: feeds }
  streams: { repository: streams }
  notes: { repository: notes }

controllers:
  members:
    service: members
    base_path: /members
    access: "*"
    operations:
      register: { access: public }
      login: { access: public }
  ledgers:
    service: ledgers
    base_path: /ledger
    access: public
    operations:
      list:
        pagination: { strategy: offset, size: { default: 2, max: 3 }, sort: [{ field: rank, dir: desc }] }
      delete: { access: owner }
  pages:
    service: pages
    base_path: /pages
    access: public
    operations:
      list:
        pagination:
          strategy: offset
          size: { default: 2, max: 3 }
          sort: [{ field: rank, dir: desc }]
          count: exact
          envelope: true
  feeds:
    service: feeds
    base_path: /feed
    access: public
    operations:
      list:
        pagination:
          strategy: keyset
          size: { default: 2, max: 3 }
          sort: [{ field: rank, dir: desc }, { field: code, dir: asc }]
          envelope: true
  streams:
    service: streams
    base_path: /stream
    access: public
    operations:
      list:
        pagination:
          strategy: keyset
          size: { default: 2, max: 3 }
          sort: [{ field: rank, dir: desc }, { field: code, dir: asc }]
  notes:
    service: notes
    base_path: /notes
    access: public

ui:
  frontend: { pack: generic, output: ./frontend, overwrite: always }
  collections:
    notes:
      fields:
        text: { from: note.body }
        code: { from: note.entry.code }
        signer: { from: note.signer.handle }
  views:
    ledger: { path: /ledger, component: crud, props: { collection: ledger } }
    members: { path: /members, component: crud, props: { collection: member } }
    signin: { path: /signin, component: auth-hero-split, props: {} }
"""

DRIVER = """
import { CREDENTIAL_FIELDS, ENTITY_FIELDS, SIGNUP_FIELDS, formValues, payload } from './fields.ts';
import { callOperation, listCollection, listRecords, readCollection, readJson } from './records.ts';

const nativeFetch = globalThis.fetch;
globalThis.fetch = (path, init) => nativeFetch(process.env.ORIGIN + path, init);

const json = { 'Content-Type': 'application/json' };
const send = (entity, operation, { body, ...request } = {}) =>
  callOperation(entity, operation, { headers: json, body: body && JSON.stringify(body), ...request }).then(readJson);
const entered = (fields, inputs) => payload(fields, { ...formValues(fields), ...inputs });

const report = {};
for (const entity of ['ledger', 'page', 'feed', 'stream']) {
  for (const rank of [0, 1, 2, 3, 4, 5, 6]) await send(entity, 'create', { body: { code: `c${rank}`, rank } });
  report[entity] = (await listRecords(entity)).map((row) => row.code);
}
const [top] = await listRecords('ledger');
report.updated = Number((await send('ledger', 'update', { id: top.id, body: { rank: 99 } })).rank);
report.fetched = Number((await send('ledger', 'get', { id: top.id })).rank);
report.anonymousDelete = await send('ledger', 'delete', { id: top.id }).catch((error) => error.message);
const ana = await send('member', 'register', { body: entered(SIGNUP_FIELDS.member, { handle: 'ana', age: '', password: 'correct-horse' }) });
const session = await send('member', 'login', { body: { handle: 'ana', password: 'correct-horse' } });
report.token = typeof session.token;
const signedIn = { ...json, Authorization: `Bearer ${session.token}` };
const newMember = { ...ENTITY_FIELDS.member, ...CREDENTIAL_FIELDS.member };
const created = await send('member', 'create', {
  headers: signedIn,
  body: entered(newMember, { handle: 'bo', age: '7', password: 'battery-staple' }),
});
report.created = [created.age, created.active];
report.createdSignsIn = typeof (await send('member', 'login', { body: { handle: 'bo', password: 'battery-staple' } })).token;
const note = await send('note', 'create', { body: { body: 'hello', entry: top.id, signer: ana.id } });
const projected = ({ id, text, code, signer }) => [id === note.id, text, code, signer ?? null];
report.projected = (await listCollection('notes')).map(projected);
report.signed = (await listCollection('notes', signedIn)).map(projected);
report.read = projected(await readCollection('notes', note.id));
console.log(JSON.stringify(report));
"""

RUNNING = re.compile(r"running on (\S+)")
UVICORN = (sys.executable, "-m", "uvicorn", "--port", "0", "--no-access-log")
DEV_SERVER = (*UVICORN, "--factory", "yaml_api_generator.server.factory:create_app")


def _context(spec: Path):
    result = load_and_generate_ir(spec)
    pack = load_pack("generic")
    return build_generator_context(result.ir, result.ui_block, pack.manifest)


def _rendered(spec: Path) -> dict[str, str]:
    pack = load_pack("generic")
    return {item.path: item.content for item in render_templates(pack, _context(spec))}


@pytest.fixture(scope="module")
def project(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("ui-records")
    (root / "spec.yaml").write_text(SPEC)
    compile_project(yaml_file=root / "spec.yaml", output_dir=root / "generated", target="fastapi")
    (root / "generated/frontend/src/__generated__/drive.mjs").write_text(DRIVER)
    return root


def test_routes_come_from_the_controllers_serving_each_entity(project):
    member = _context(project / "spec.yaml").entities["member"]

    assert {operation: (route.method, route.path) for operation, route in member.routes.items()} == {
        "list": ("GET", "/members"),
        "get": ("GET", "/members/{id}"),
        "create": ("POST", "/members"),
        "update": ("PATCH", "/members/{id}"),
        "delete": ("DELETE", "/members/{id}"),
        "register": ("POST", "/members/register"),
        "login": ("POST", "/members/login"),
    }
    assert member.serves_login
    assert [field.name for field in member.signup_fields] == ["handle", "age", "active", "password"]


def test_identity_without_login_registers_through_its_public_create():
    user = _context(EXAMPLES / "valid/blog-with-ui.yaml").entities["user"]

    assert not user.serves_login
    assert user.routes["register"] == user.routes["create"]


def test_pagination_comes_from_the_list_route(project):
    entities = _context(project / "spec.yaml").entities

    assert {name: (entity.pagination.strategy, entity.pagination.envelope) for name, entity in entities.items()
            if entity.pagination} == {
        "ledger": ("offset", False),
        "page": ("offset", True),
        "feed": ("keyset", True),
        "stream": ("keyset", False),
    }


def test_roles_carry_the_entity_level_hierarchy():
    roles = _context(EXAMPLES / "v02/api-with-admin.yaml").entities["user"].roles

    assert roles.default == "user"
    assert roles.field == "role"
    assert roles.includes == {"admin": ("moderator", "user"), "moderator": ("user",), "user": ()}


def test_access_verdicts_follow_the_route_rules():
    entities = _context(EXAMPLES / "v02/api-with-admin.yaml").entities
    blog = _context(EXAMPLES / "valid/blog-with-ui.yaml").entities

    assert entities["post"].access["delete"] == {
        "anonymous": "deny",
        "user.admin": "allow",
        "user.moderator": "deny",
        "user.user": "deny",
    }
    assert entities["post"].access["list"]["anonymous"] == "allow"
    assert blog["post"].access["update"] == {"anonymous": "deny", "user": "conditional"}


def test_entities_without_an_edit_route_expose_no_edit_operation():
    entities = _context(EXAMPLES / "valid/blog-with-ui.yaml").entities

    assert entities["post"].edit_operation == "update"
    assert entities["comment"].edit_operation is None


def test_pages_reach_the_api_only_through_declared_routes(project):
    frontend = project / "generated/frontend/src"
    pages = {path.name: path.read_text() for path in (frontend / "pages").iterdir()}
    records = (frontend / "__generated__/records.ts").read_text()

    assert not [name for name, page in pages.items() if "API_BASE_URL" in page or "fetch(" in page]
    assert 'login: { method: "POST", path: "/members/login" }' in records
    assert 'register: { method: "POST", path: "/members/register" }' in records


def test_sign_in_submits_the_declared_identifier(project):
    generated = project / "generated/frontend/src"
    app = (generated / "__generated__/App.tsx").read_text()

    assert "callOperation('member', 'login'" in app
    assert "handle: identifier" in app
    assert 'login(String(values["handle"])' in (generated / "pages/Signin.tsx").read_text()


def test_sign_up_and_new_identity_forms_send_typed_fields_and_credentials(project):
    generated = project / "generated/frontend/src"
    form = (generated / "pages/MembersForm.tsx").read_text()
    auth = (generated / "__generated__/auth.tsx").read_text()
    hook = (generated / "__generated__/useRecordForm.ts").read_text()

    assert re.search(r"\{mode === 'create' && \(\s*<div className=\"wf-field\">\s*<label htmlFor=\"password\"", form)
    assert 'type="password"' in form
    assert "...CREDENTIAL_FIELDS[entity]" in hook
    assert "payload(FIELDS, mode === 'login'" in auth

def test_specs_without_login_render_no_sign_in():
    files = _rendered(EXAMPLES / "v03/crud-pagination/spec.yaml")

    assert not [path for path in files if path.endswith("auth.tsx")]
    assert "login" not in files[next(path for path in files if path.endswith("App.tsx"))]


def _origin(server: subprocess.Popen) -> str:
    log = []
    for line in server.stderr:
        if match := RUNNING.search(line):
            return match[1]
        log.append(line)
    raise AssertionError("".join(log))


@contextmanager
def _serving(command: tuple[str, ...], cwd: Path, env: dict[str, str]) -> Iterator[str]:
    server = subprocess.Popen(command, cwd=cwd, env={**os.environ, **env}, stderr=subprocess.PIPE, text=True)
    try:
        yield _origin(server)
    finally:
        server.terminate()
        server.wait()


SERVERS = {
    "dev-fastapi": lambda project, workdir: _serving(
        DEV_SERVER, workdir, {SPEC_ENV: str(project / "spec.yaml"), RAW_ENV: "0"}
    ),
    "dev-raw": lambda project, workdir: _serving(
        DEV_SERVER, workdir, {SPEC_ENV: str(project / "spec.yaml"), RAW_ENV: "1"}
    ),
    "generated-fastapi": lambda project, workdir: _serving(
        (*UVICORN, "app:app"),
        project / "generated/backend",
        {
            "DATABASE_URL": f"sqlite+aiosqlite:///{workdir / 'records.sqlite'}",
            "JWT_SECRET": "ui-records-signing-key-of-32-bytes",
        },
    ),
}


@pytest.mark.skipif(shutil.which("node") is None, reason="node runs the generated data layer")
@pytest.mark.parametrize("server", SERVERS)
def test_generated_data_layer_drives_every_server(project, tmp_path, server):
    with SERVERS[server](project, tmp_path) as origin:
        result = subprocess.run(
            ["node", "--experimental-strip-types", "--no-warnings", "drive.mjs"],
            cwd=project / "generated/frontend/src/__generated__",
            env={**os.environ, "ORIGIN": origin},
            capture_output=True,
            text=True,
        )

    assert result.returncode == 0, result.stderr
    every_row = ["c6", "c5", "c4", "c3", "c2", "c1", "c0"]
    assert json.loads(result.stdout) == {
        "ledger": every_row,
        "page": every_row,
        "feed": every_row,
        "stream": every_row,
        "updated": 99,
        "fetched": 99,
        "anonymousDelete": "Authentication required",
        "token": "string",
        "created": [7, True],
        "createdSignsIn": "string",
        "projected": [[True, "hello", "c6", None]],
        "signed": [[True, "hello", "c6", "ana"]],
        "read": [True, "hello", "c6", None],
    }
