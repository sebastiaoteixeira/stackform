"""Invalid specs are rejected by generic JSON-schema validation before any transform runs."""

import copy
from pathlib import Path

import pytest
import yaml

from yaml_api_generator.parsers.yaml_parser import ConfigErrors, load_and_generate_ir

EXAMPLES_INVALID = Path(__file__).parents[2] / "examples" / "invalid"

FIELDS = {"id": {"type": "id"}, "title": {"type": "string"}}

BASE_SPECS = {
    "0.1": {"version": "0.1", "collections": {"posts": {"fields": FIELDS}}},
    **{
        version: {
            "version": version,
            "api": {"basePath": "/api"},
            "entities": {"post": {"fields": FIELDS}},
            "repositories": {"posts": {"entity": "post"}},
            "services": {"posts": {"repository": "posts"}},
            "controllers": {
                "posts": {"service": "posts", "base_path": "/posts", "access": [{"then": "allow"}]}
            },
        }
        for version in ("0.2", "0.3")
    },
}

OIDC_V01 = {"type": "oidc", "client_id": "id", "client_secret": "secret"}
SAML = {"type": "saml", "idp_metadata_url": "https://idp/metadata", "sp_entity_id": "sp"}
ACCESS_RULE = ("controllers", "posts", "access", 0)
ROLES = {"values": ["reader"], "default": "reader"}
TITLE = ("fields", "title")

# (versions, path, value, message fragment)
REJECTED = {
    "options": (("0.1", "0.2", "0.3"), ("options",), {"strict": True}, "'options' was unexpected"),
    "security-redaction": (("0.1",), ("security", "redaction"), {}, "'redaction' was unexpected"),
    "oidc-discovery-url": (
        ("0.1",), ("providers", "corp"), {**OIDC_V01, "discovery_url": "https://idp"}, "'discovery_url' was unexpected"
    ),
    "oidc-claim-mapping": (
        ("0.1",), ("providers", "corp"), {**OIDC_V01, "claim_mapping": {}}, "'claim_mapping' was unexpected"
    ),
    "oidc-auto-provision": (
        ("0.1",), ("providers", "corp"), {**OIDC_V01, "auto_provision": True}, "'auto_provision' was unexpected"
    ),
    "indexes": (("0.1",), ("collections", "posts", "indexes"), [], "'indexes' was unexpected"),
    "v01-field-store": (("0.1",), ("collections", "posts", *TITLE, "store"), True, "'store' was unexpected"),
    "v01-field-expand": (("0.1",), ("collections", "posts", *TITLE, "expand"), True, "'expand' was unexpected"),
    "field-store": (("0.2", "0.3"), ("entities", "post", *TITLE, "store"), True, "'store' was unexpected"),
    "field-expand": (("0.2", "0.3"), ("entities", "post", *TITLE, "expand"), True, "'expand' was unexpected"),
    "access-filter": (("0.2", "0.3"), (*ACCESS_RULE, "filter"), "owner = principal.sub", "'filter' was unexpected"),
    "access-write-fields": (("0.2", "0.3"), (*ACCESS_RULE, "writeFields"), ["title"], "'writeFields' was unexpected"),
    "top-level-roles": (("0.2", "0.3"), ("roles",), {"user": {"admin": ["user"]}}, "'roles' was unexpected"),
    "register-in-defaults": (
        ("0.2", "0.3"), ("api", "operations", "defaults", "register"), True, "'register' was unexpected"
    ),
    "crud-in-auth": (("0.2", "0.3"), ("api", "operations", "auth", "list"), True, "'list' was unexpected"),
    "saml-issuer": (("0.2", "0.3"), ("providers", "corp"), {**SAML, "issuer": "x"}, "'issuer' was unexpected"),
    "saml-audience": (("0.2", "0.3"), ("providers", "corp"), {**SAML, "audience": "x"}, "'audience' was unexpected"),
    "saml-trust": (("0.2", "0.3"), ("providers", "corp"), {**SAML, "trust": "idp"}, "'trust' was unexpected"),
    "api-name": (("0.2", "0.3"), ("api", "name"), "blog", "'name' was unexpected"),
    "root-input": (("0.3",), ("input",), ["orgId"], "'input' was unexpected"),
    "auth-bindings": (
        ("0.2", "0.3"),
        ("entities", "post", "auth"),
        {"identifier": "title", "via": "password", "bindings": [{"provider": "corp"}]},
        "'bindings' was unexpected",
    ),
    "import-string-form": (("0.3",), ("imports", "helpers"), "helpers.py", "is not of type 'object'"),
    "cors-credentials-any-origin": (
        ("0.1",),
        ("security", "cors"),
        {"allowedOrigins": ["*"], "allowCredentials": True},
        "should not be valid under",
    ),
    "typo-root": (("0.1", "0.2", "0.3"), ("colections",), {}, "'colections' was unexpected"),
    "typo-field": (("0.2", "0.3"), ("entities", "post", *TITLE, "requird"), True, "'requird' was unexpected"),
    "v01-max-page-size-zero": (("0.1",), ("api", "pagination", "maxPageSize"), 0, "less than the minimum of 1"),
    "v01-default-page-size-negative": (
        ("0.1",), ("api", "pagination", "defaultPageSize"), -1, "less than the minimum of 1"
    ),
    "v01-via-empty": (
        ("0.1",), ("collections", "posts", "auth"), {"identifier": "title", "via": []}, "is not valid under any"
    ),
    "v01-roles-on-base-collection": (("0.1",), ("collections", "posts", "roles"), ROLES, "'type' is a required property"),
    "roles-on-base-entity": (("0.2", "0.3"), ("entities", "post", "roles"), ROLES, "'type' is a required property"),
    "deploy-port-zero": (("0.2", "0.3"), ("deploy",), {"runtime": "docker", "port": 0}, "less than the minimum of 1"),
    "deploy-port-negative": (("0.2", "0.3"), ("deploy",), {"runtime": "docker", "port": -5}, "less than the minimum of 1"),
    "deploy-port-above-range": (
        ("0.2", "0.3"), ("deploy",), {"runtime": "docker", "port": 65536}, "greater than the maximum of 65535"
    ),
}

CASES = [
    pytest.param(version, path, value, fragment, id=f"{name}-{version}")
    for name, (versions, path, value, fragment) in REJECTED.items()
    for version in versions
]

# Top-level blocks authored as a list or scalar must not reach desugar.
WRONG_SHAPES = {
    "entities-string": ({"entities": "foo"}, "entities"),
    "entities-list": ({"entities": ["a"]}, "entities"),
    "repositories-list": ({"repositories": ["a"]}, "repositories"),
    "services-list": ({"services": ["a"]}, "services"),
    "api-scalar": ({"api": "foo"}, "api"),
    "api-operations-list": ({"api": {"operations": ["a"]}}, "api.operations"),
}


def _set_path(spec: dict, path: tuple, value) -> dict:
    *parents, leaf = path
    node = spec
    for key in parents:
        node = node[key] if isinstance(key, int) else node.setdefault(key, {})
    node[leaf] = value
    return spec


def _load_errors(tmp_path, spec: dict) -> list:
    path = tmp_path / "spec.yaml"
    path.write_text(yaml.safe_dump(spec))
    with pytest.raises(ConfigErrors) as exc_info:
        load_and_generate_ir(str(path))
    return exc_info.value.errors


@pytest.mark.parametrize("version", BASE_SPECS)
def test_base_specs_load(tmp_path, version):
    path = tmp_path / "spec.yaml"
    path.write_text(yaml.safe_dump(BASE_SPECS[version]))
    assert load_and_generate_ir(str(path)).ir.version == version


@pytest.mark.parametrize(("version", "path", "value", "fragment"), CASES)
def test_schema_rejects_unknown_or_removed_key(tmp_path, version, path, value, fragment):
    spec = _set_path(copy.deepcopy(BASE_SPECS[version]), path, value)
    errors = _load_errors(tmp_path, spec)
    assert {error.code for error in errors} == {"SCHEMA_VALIDATION_ERROR"}
    assert any(fragment in error.message for error in errors)


MONGO = {"uri": "mongodb://localhost:27017", "database": "blog"}
POSTGRES = {"type": "postgres", "dsn": "postgresql+asyncpg://localhost/blog", "default": True}
FILESYSTEM = {"type": "filesystem", "path": "./uploads"}


@pytest.mark.parametrize("version", ["0.2", "0.3"])
def test_mongo_block_beside_record_datastores_rejected(tmp_path, version):
    spec = {**BASE_SPECS[version], "mongo": MONGO, "datastores": {"main": POSTGRES}}
    errors = _load_errors(tmp_path, spec)
    assert [(error.code, error.path) for error in errors] == [("SCHEMA_VALIDATION_ERROR", "mongo")]
    assert "mutually exclusive" in errors[0].message


def test_mongo_block_beside_file_datastores_accepted(tmp_path):
    path = tmp_path / "spec.yaml"
    path.write_text(yaml.safe_dump({**BASE_SPECS["0.3"], "mongo": MONGO, "datastores": {"disk": FILESYSTEM}}))
    assert load_and_generate_ir(str(path)).ir.mongo.database == "blog"


@pytest.mark.parametrize("spec,path", WRONG_SHAPES.values(), ids=list(WRONG_SHAPES))
def test_wrong_container_shape_reports_schema_error(tmp_path, spec, path):
    errors = _load_errors(tmp_path, {"version": "0.2", **spec})
    assert any(e.code == "SCHEMA_VALIDATION_ERROR" and e.path == path for e in errors)


@pytest.mark.parametrize(
    "name", ["access-control-patterns.yaml", "advanced-operations.yaml", "multi-tenant.yaml"]
)
def test_invalid_examples_report_schema_errors_instead_of_crashing(name):
    with pytest.raises(ConfigErrors) as exc_info:
        load_and_generate_ir(str(EXAMPLES_INVALID / name))
    assert {error.code for error in exc_info.value.errors} == {"SCHEMA_VALIDATION_ERROR"}
