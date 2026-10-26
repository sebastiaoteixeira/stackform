"""A document binding, in a rule's ``given`` or as a policy argument, names a known collection."""

import pytest

from yaml_api_generator.parsers.yaml_parser import ConfigErrors, load_and_generate_ir

SPEC = """
version: "{version}"
api:
  basePath: /api
mongo: {{ uri: "mongodb://localhost", database: blog }}
policies:
  ownsPost:
    given: {{ parent: "posts by postId" }}
    params: [who]
    when: parent.ownerId equals who.sub
entities:
  user:
    type: auth
    auth: {{ identifier: email, via: password }}
    fields:
      id: {{ type: id }}
      email: {{ type: string, required: true, unique: true }}
  post:
    fields:
      id: {{ type: id }}
      ownerId: {{ type: string }}
repositories:
  users: {{ entity: user }}
  posts: {{ entity: post }}
services:
  users: {{ repository: users }}
  posts: {{ repository: posts }}
controllers:
  users: {{ service: users, base_path: /users, access: public }}
  owned:
    base_path: /owned
    routes:
      get:
        service: posts
        method: GET
        path: /{{postId}}
        access:
          - given: {given}
            when: "{when}"
"""

VERSIONS = pytest.mark.parametrize("version", ["0.2", "0.3"])


def _parse(tmp_path, version, given, when):
    path = tmp_path / "spec.yaml"
    path.write_text(SPEC.format(version=version, given=given, when=when))
    return load_and_generate_ir(path)


def _refusals(tmp_path, version, given, when):
    with pytest.raises(ConfigErrors) as raised:
        _parse(tmp_path, version, given, when)
    return [(error.code, error.message) for error in raised.value.errors]


@VERSIONS
def test_policy_argument_naming_a_rule_symbol_is_refused(tmp_path, version):
    given = '{ principal: "identity:user" }'
    assert _refusals(tmp_path, version, given, "policy:ownsPost(principal)") == [
        ("DOCUMENT_BINDING_INVALID", "document binding references unknown collection 'principal'")
    ]


@VERSIONS
def test_given_naming_an_unknown_collection_is_refused(tmp_path, version):
    given = '{ principal: "identity:user", draft: drafts }'
    assert _refusals(tmp_path, version, given, "draft.ownerId equals principal.sub") == [
        ("DOCUMENT_BINDING_INVALID", "document binding references unknown collection 'drafts'")
    ]


@VERSIONS
def test_policy_argument_binding_the_identity_is_accepted(tmp_path, version):
    given = '{ principal: "identity:user" }'
    assert _parse(tmp_path, version, given, "policy:ownsPost(identity:user)").ir.routes
