"""Tests for v0.3 service ``input:`` validation and ``with:`` forwarding (issue #59).

A service declares the inputs it requires (an inline field map or named DTOs);
they are type-validated before the service runs so a bad input aborts with 422
and nothing downstream executes. ``with:`` forwards the validated inputs to a
repository operation (populating its free-symbols) or to a handler, its
right-hand-side ``$symbols`` resolving against the input field names -- an
unbound reference aborts generation with UNDEFINED_SYMBOL. v0.2 specs never carry
either construct and stay byte-identical.
"""

import textwrap

import pytest

from yaml_api_generator.ir import IRLiteralRef, IRSymbolRef, IRServiceInput
from yaml_api_generator.parsers.service_input_parser import (
    parse_service_input,
    parse_service_with,
)
from yaml_api_generator.parsers.transformers.symbol_validation import validate_spec_symbols
from yaml_api_generator.parsers.yaml_parser import ConfigErrors, load_and_generate_ir
from yaml_api_generator.server.common.request_context import RequestContext
from yaml_api_generator.server.common.steps.services import ServiceInputStep


def _codes(errors):
    return {error.code for error in errors}


# --- parser ---------------------------------------------------------------


def test_parse_inline_input_normalizes_types():
    parsed, errors = parse_service_input({"postId": "string", "count": "number"}, {}, "p")
    assert errors == []
    assert parsed == IRServiceInput(
        fields={"postId": {"type": "string"}, "count": {"type": "number"}}
    )
    assert parsed.names == {"postId", "count"}


def test_parse_input_merges_named_dtos():
    dtos = {"PostRef": {"fields": {"id": {"type": "string"}}}}
    parsed, errors = parse_service_input(["PostRef"], dtos, "p")
    assert errors == []
    assert parsed.fields == {"id": {"type": "string"}}


def test_parse_input_undefined_dto_aborts():
    parsed, errors = parse_service_input(["Ghost"], {}, "p")
    assert parsed is None
    assert _codes(errors) == {"SERVICE_INPUT_DTO_NOT_FOUND"}


def test_parse_input_invalid_shape_aborts():
    _, errors = parse_service_input("PostRef", {}, "p")
    assert _codes(errors) == {"SERVICE_INPUT_INVALID"}


def test_parse_with_symbols_and_literals():
    parsed, errors = parse_service_with(
        {"id": "$postId", "status": "'open'", "count": "3"}, "p"
    )
    assert errors == []
    assert parsed == {
        "id": IRSymbolRef(root="postId"),
        "status": IRLiteralRef("open"),
        "count": IRLiteralRef(3),
    }


# --- build-time symbol resolution -----------------------------------------


def _with_spec(inputs, forwarding):
    return {
        "version": "0.3",
        "services": {
            "archive": {
                "repository": "posts",
                "operation": "archive",
                "input": inputs,
                "with": forwarding,
            }
        },
    }


def test_with_rhs_bound_to_input_resolves():
    spec = _with_spec({"postId": "string"}, {"id": "$postId"})
    assert validate_spec_symbols(spec) == []


def test_with_rhs_unbound_aborts_with_undefined_symbol():
    spec = _with_spec({"postId": "string"}, {"id": "$ghost"})
    errors = validate_spec_symbols(spec)
    assert _codes(errors) == {"UNDEFINED_SYMBOL"}
    assert "$ghost" in errors[0].message
    assert "service 'archive' with 'id'" in errors[0].message


def test_with_literal_needs_no_input():
    spec = _with_spec({"postId": "string"}, {"status": "'archived'"})
    assert validate_spec_symbols(spec) == []


# --- transformer / IR end to end ------------------------------------------


_SPEC = """
version: "0.3"
api:
  name: test
  basePath: /api
entities:
  post:
    fields:
      id:
        type: id
      title:
        type: string
repositories:
  posts:
    entity: post
    operations:
      archive:
        query:
          command: find
          filter:
            postId: "$postId"
services:
  archive:
    repository: posts
    operation: archive
    input:
      postId: string
    with:
      postId: $postId
controllers:
  posts:
    base_path: /posts
    routes:
      archive:
        service: archive
        method: POST
        path: "/{postId}/archive"
"""


def _load(tmp_path, spec=_SPEC):
    path = tmp_path / "spec.yaml"
    path.write_text(textwrap.dedent(spec))
    return load_and_generate_ir(str(path))


def test_service_input_and_forwarding_reach_ir(tmp_path):
    document = _load(tmp_path).ir
    service = document.services["archive"]
    assert service.input == IRServiceInput(fields={"postId": {"type": "string"}})
    assert service.forwarding == {"postId": IRSymbolRef(root="postId")}


def test_unbound_forwarding_aborts_end_to_end(tmp_path):
    broken = _SPEC.replace("postId: $postId\n", "postId: $ghost\n")
    with pytest.raises(ConfigErrors) as exc_info:
        _load(tmp_path, broken)
    assert any(e.code == "UNDEFINED_SYMBOL" for e in exc_info.value.errors)


# --- runtime step ---------------------------------------------------------


def _ctx(url_params, body=None):
    return RequestContext(
        method="POST",
        path="/posts/{postId}/archive",
        api_version=None,
        collection="posts",
        operation="archive",
        headers={},
        url_params=url_params,
        repository=None,
        principal=None,
        body=body,
        response=None,
    )


def test_runtime_forwards_symbol_from_path_into_params():
    step = ServiceInputStep(
        {"postId": {"type": "string"}}, {"id": IRSymbolRef(root="postId")}
    )
    ctx = step(_ctx({"postId": "p1"}))
    assert ctx.service_inputs == {"id": "p1"}
    assert ctx.url_params["id"] == "p1"


def test_runtime_forwards_symbol_from_body():
    step = ServiceInputStep(
        {"count": {"type": "number"}}, {"total": IRSymbolRef(root="count")}
    )
    ctx = step(_ctx({}, body={"count": 7}))
    assert ctx.service_inputs == {"total": 7}


def test_runtime_literal_forwarding_needs_no_input():
    step = ServiceInputStep({}, {"status": IRLiteralRef("archived")})
    ctx = step(_ctx({}))
    assert ctx.service_inputs == {"status": "archived"}


def test_runtime_missing_input_is_422():
    step = ServiceInputStep({"postId": {"type": "string"}}, {})
    with pytest.raises(ValueError):
        step(_ctx({}))


def test_runtime_ill_typed_input_is_422():
    step = ServiceInputStep({"count": {"type": "number"}}, {})
    with pytest.raises(ValueError):
        step(_ctx({}, body={"count": "not-a-number"}))
