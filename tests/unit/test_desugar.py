import copy

import pytest

from yaml_api_generator.parsing.desugar import desugar_v02
from yaml_api_generator.parsing.parser import ConfigErrors


def _base_config() -> dict:
    return {
        "api": {
            "basePath": "/api",
            "version": "v1",
            "operations": {
                "defaults": {
                    "list": True,
                    "get": True,
                    "create": True,
                    "update": True,
                    "replace": False,
                    "delete": True,
                },
                "auth": {
                    "register": True,
                    "login": True,
                },
            },
        },
        "mongo": {"uri": "mongodb://localhost:27017", "database": "testdb"},
        "entities": {},
        "repositories": {},
        "services": {},
        "controllers": {},
    }


def _with_entity(name: str, **kwargs) -> dict:
    config = _base_config()
    config["entities"][name] = kwargs
    return config


# --- Entity Inheritance (30-39) ---


def test_entity_no_extends_unchanged():
    config = _with_entity(
        "post",
        fields={"id": {"type": "id"}, "title": {"type": "string"}},
    )
    original = copy.deepcopy(config["entities"]["post"])
    result = desugar_v02(config)
    assert result["entities"]["post"]["fields"] == original["fields"]


def test_single_level_extends_fields_merged():
    config = _base_config()
    config["entities"]["base"] = {
        "fields": {"id": {"type": "id"}, "createdAt": {"type": "datetime"}},
    }
    config["entities"]["post"] = {
        "extends": "base",
        "fields": {"title": {"type": "string"}},
    }
    result = desugar_v02(config)
    fields = result["entities"]["post"]["fields"]
    assert "id" in fields
    assert "createdAt" in fields
    assert "title" in fields


def test_single_level_extends_child_overrides_parent():
    config = _base_config()
    config["entities"]["base"] = {
        "fields": {"title": {"type": "string", "required": False}},
    }
    config["entities"]["post"] = {
        "extends": "base",
        "fields": {"title": {"type": "string", "required": True}},
    }
    result = desugar_v02(config)
    assert result["entities"]["post"]["fields"]["title"]["required"] is True


def test_multi_level_extends_transitive():
    config = _base_config()
    config["entities"]["a"] = {
        "fields": {"id": {"type": "id"}},
    }
    config["entities"]["b"] = {
        "extends": "a",
        "fields": {"name": {"type": "string"}},
    }
    config["entities"]["c"] = {
        "extends": "b",
        "fields": {"age": {"type": "number"}},
    }
    result = desugar_v02(config)
    fields = result["entities"]["c"]["fields"]
    assert "id" in fields
    assert "name" in fields
    assert "age" in fields


def test_type_inherited_from_parent():
    config = _base_config()
    config["entities"]["base_auth"] = {
        "type": "auth",
        "fields": {"id": {"type": "id"}},
    }
    config["entities"]["user"] = {
        "extends": "base_auth",
        "fields": {"email": {"type": "string"}},
    }
    result = desugar_v02(config)
    assert result["entities"]["user"]["type"] == "auth"


def test_auth_config_inherited_deep_copy():
    config = _base_config()
    auth_cfg = {"identifier": "email", "via": "password"}
    config["entities"]["base_auth"] = {
        "type": "auth",
        "auth": auth_cfg,
        "fields": {"id": {"type": "id"}},
    }
    config["entities"]["user"] = {
        "extends": "base_auth",
        "fields": {"email": {"type": "string"}},
    }
    config["entities"]["admin"] = {
        "extends": "base_auth",
        "fields": {"email": {"type": "string"}},
    }
    result = desugar_v02(config)
    user_auth = result["entities"]["user"]["auth"]
    admin_auth = result["entities"]["admin"]["auth"]
    assert user_auth is not admin_auth
    assert user_auth == admin_auth


def test_extends_key_stripped_after_merging():
    config = _base_config()
    config["entities"]["base"] = {"fields": {"id": {"type": "id"}}}
    config["entities"]["child"] = {
        "extends": "base",
        "fields": {"name": {"type": "string"}},
    }
    result = desugar_v02(config)
    assert "extends" not in result["entities"]["child"]


def test_extends_self_circular_error():
    config = _base_config()
    config["entities"]["self_ref"] = {
        "extends": "self_ref",
        "fields": {"id": {"type": "id"}},
    }
    with pytest.raises(ConfigErrors) as exc_info:
        desugar_v02(config)
    assert any(e.code == "ENTITY_CIRCULAR_EXTENDS" for e in exc_info.value.errors)


def test_circular_chain_a_b_a_error():
    config = _base_config()
    config["entities"]["a"] = {
        "extends": "b",
        "fields": {"id": {"type": "id"}},
    }
    config["entities"]["b"] = {
        "extends": "a",
        "fields": {"id": {"type": "id"}},
    }
    with pytest.raises(ConfigErrors) as exc_info:
        desugar_v02(config)
    assert any(e.code == "ENTITY_CIRCULAR_EXTENDS" for e in exc_info.value.errors)


def test_extends_nonexistent_error():
    config = _base_config()
    config["entities"]["child"] = {
        "extends": "ghost",
        "fields": {"id": {"type": "id"}},
    }
    with pytest.raises(ConfigErrors) as exc_info:
        desugar_v02(config)
    assert any(e.code == "ENTITY_EXTENDS_NOT_FOUND" for e in exc_info.value.errors)


def test_non_dict_entity_value_skipped():
    config = _base_config()
    config["entities"]["bad"] = "not a dict"
    config["entities"]["post"] = {"fields": {"id": {"type": "id"}}}
    result = desugar_v02(config)
    assert result["entities"]["bad"] == "not a dict"


# --- Abstract Entities (40-43) ---


def test_abstract_entity_removed_after_desugaring():
    config = _base_config()
    config["entities"]["base"] = {
        "abstract": True,
        "fields": {"id": {"type": "id"}},
    }
    config["entities"]["post"] = {
        "extends": "base",
        "fields": {"title": {"type": "string"}},
    }
    config["repositories"]["posts"] = {"entity": "post"}
    result = desugar_v02(config)
    assert "base" not in result["entities"]


def test_abstract_entity_referenced_by_repo_error():
    config = _base_config()
    config["entities"]["base"] = {
        "abstract": True,
        "fields": {"id": {"type": "id"}},
    }
    config["repositories"]["bases"] = {"entity": "base"}
    with pytest.raises(ConfigErrors) as exc_info:
        desugar_v02(config)
    assert any(e.code == "DESUGAR_ABSTRACT_REFERENCED" for e in exc_info.value.errors)


def test_abstract_entity_not_referenced_silently_removed():
    config = _base_config()
    config["entities"]["template"] = {
        "abstract": True,
        "fields": {"id": {"type": "id"}, "name": {"type": "string"}},
    }
    config["entities"]["post"] = {"fields": {"id": {"type": "id"}}}
    result = desugar_v02(config)
    assert "template" not in result["entities"]
    assert "post" in result["entities"]


def test_abstract_key_stripped_from_non_abstract():
    config = _base_config()
    config["entities"]["base"] = {
        "abstract": True,
        "fields": {"id": {"type": "id"}},
    }
    config["entities"]["post"] = {
        "extends": "base",
        "fields": {"title": {"type": "string"}},
    }
    config["repositories"]["posts"] = {"entity": "post"}
    result = desugar_v02(config)
    assert "abstract" not in result["entities"]["post"]


# --- Service Expansion (44-58) ---


def test_minified_service_with_repository_key_expanded():
    config = _base_config()
    config["entities"]["post"] = {"fields": {"id": {"type": "id"}}}
    config["repositories"]["posts"] = {"entity": "post"}
    config["services"]["posts"] = {"repository": "posts"}
    result = desugar_v02(config)
    assert "posts" not in result["services"]
    assert "list-posts" in result["services"]
    assert result["services"]["list-posts"]["operation"] == "list"
    assert result["services"]["list-posts"]["repository"] == "posts"


def test_minified_service_by_key_name_expanded():
    config = _base_config()
    config["entities"]["post"] = {"fields": {"id": {"type": "id"}}}
    config["repositories"]["posts"] = {"entity": "post"}
    config["services"]["posts"] = {}
    result = desugar_v02(config)
    assert "posts" not in result["services"]
    assert "list-posts" in result["services"]


def test_already_expanded_service_passed_through():
    config = _base_config()
    config["services"]["my-handler"] = {"handler": "do_something"}
    result = desugar_v02(config)
    assert result["services"]["my-handler"]["handler"] == "do_something"


def test_service_with_explicit_repo_name():
    config = _base_config()
    config["entities"]["post"] = {"fields": {"id": {"type": "id"}}}
    config["repositories"]["my_posts_repo"] = {"entity": "post"}
    config["services"]["posts"] = {"repository": "my_posts_repo"}
    result = desugar_v02(config)
    svc = result["services"]["list-posts"]
    assert svc["repository"] == "my_posts_repo"


def test_repo_not_found_error():
    config = _base_config()
    config["services"]["posts"] = {"repository": "nonexistent"}
    with pytest.raises(ConfigErrors) as exc_info:
        desugar_v02(config)
    assert any(e.code == "DESUGAR_REPO_NOT_FOUND" for e in exc_info.value.errors)


def test_repo_with_no_entity_error():
    config = _base_config()
    config["repositories"]["posts"] = {}
    config["services"]["posts"] = {}
    with pytest.raises(ConfigErrors) as exc_info:
        desugar_v02(config)
    assert any(e.code == "DESUGAR_ENTITY_NOT_FOUND" for e in exc_info.value.errors)


def test_entity_not_found_for_repo_error():
    config = _base_config()
    config["repositories"]["posts"] = {"entity": "ghost"}
    config["services"]["posts"] = {}
    with pytest.raises(ConfigErrors) as exc_info:
        desugar_v02(config)
    assert any(e.code == "DESUGAR_ENTITY_NOT_FOUND" for e in exc_info.value.errors)


def test_crud_op_true_expanded():
    config = _base_config()
    config["entities"]["post"] = {"fields": {"id": {"type": "id"}}}
    config["repositories"]["posts"] = {"entity": "post"}
    config["services"]["posts"] = {"repository": "posts"}
    result = desugar_v02(config)
    assert "create-posts" in result["services"]
    assert result["services"]["create-posts"]["operation"] == "create"
    assert result["services"]["create-posts"]["repository"] == "posts"


def test_crud_op_false_skipped():
    config = _base_config()
    config["api"]["operations"]["defaults"]["replace"] = False
    config["entities"]["post"] = {"fields": {"id": {"type": "id"}}}
    config["repositories"]["posts"] = {"entity": "post"}
    config["services"]["posts"] = {"repository": "posts"}
    result = desugar_v02(config)
    assert "replace-posts" not in result["services"]


def test_crud_op_dict_with_handler():
    config = _base_config()
    config["entities"]["post"] = {"fields": {"id": {"type": "id"}}}
    config["repositories"]["posts"] = {"entity": "post"}
    config["services"]["posts"] = {
        "repository": "posts",
        "operations": {
            "create": {"handler": "posts.custom_create"},
        },
    }
    result = desugar_v02(config)
    assert "create-posts" in result["services"]
    assert result["services"]["create-posts"]["handler"] == "posts.custom_create"


def test_crud_op_dict_without_handler_skipped():
    config = _base_config()
    config["entities"]["post"] = {"fields": {"id": {"type": "id"}}}
    config["repositories"]["posts"] = {"entity": "post"}
    config["services"]["posts"] = {
        "repository": "posts",
        "operations": {
            "create": {"some_other_key": True},
        },
    }
    result = desugar_v02(config)
    assert "create-posts" not in result["services"]


def test_auth_ops_generated_for_auth_entity():
    config = _base_config()
    config["entities"]["user"] = {
        "type": "auth",
        "fields": {"id": {"type": "id"}, "email": {"type": "string"}},
    }
    config["repositories"]["users"] = {"entity": "user"}
    config["services"]["users"] = {"repository": "users"}
    result = desugar_v02(config)
    assert "register-users" in result["services"]
    assert "login-users" in result["services"]
    assert result["services"]["register-users"]["operation"] == "create"
    assert result["services"]["login-users"]["operation"] == "login"


def test_auth_ops_not_generated_for_non_auth_entity():
    config = _base_config()
    config["entities"]["post"] = {"fields": {"id": {"type": "id"}}}
    config["repositories"]["posts"] = {"entity": "post"}
    config["services"]["posts"] = {"repository": "posts"}
    result = desugar_v02(config)
    assert "register-posts" not in result["services"]
    assert "login-posts" not in result["services"]


def test_auth_op_with_custom_handler():
    config = _base_config()
    config["entities"]["user"] = {
        "type": "auth",
        "fields": {"id": {"type": "id"}, "email": {"type": "string"}},
    }
    config["repositories"]["users"] = {"entity": "user"}
    config["services"]["users"] = {
        "repository": "users",
        "operations": {
            "register": {"handler": "auth.custom_register"},
        },
    }
    result = desugar_v02(config)
    assert "register-users" in result["services"]
    assert result["services"]["register-users"]["handler"] == "auth.custom_register"


def test_operation_defaults_layered_global_repo_service():
    config = _base_config()
    config["api"]["operations"]["defaults"]["replace"] = False
    config["entities"]["post"] = {"fields": {"id": {"type": "id"}}}
    config["repositories"]["posts"] = {
        "entity": "post",
        "operations": {"replace": True},
    }
    config["services"]["posts"] = {
        "repository": "posts",
        "operations": {"replace": False},
    }
    result = desugar_v02(config)
    assert "replace-posts" not in result["services"]


# --- Repository Desugaring (59) ---


def test_operations_key_stripped_from_repositories():
    config = _base_config()
    config["entities"]["post"] = {"fields": {"id": {"type": "id"}}}
    config["repositories"]["posts"] = {
        "entity": "post",
        "operations": {"replace": True},
    }
    config["services"]["posts"] = {"repository": "posts"}
    result = desugar_v02(config)
    assert "operations" not in result["repositories"]["posts"]


# --- Controller Desugaring (60-69) ---


def _config_with_controller() -> dict:
    config = _base_config()
    config["entities"]["post"] = {"fields": {"id": {"type": "id"}}}
    config["repositories"]["posts"] = {"entity": "post"}
    config["services"]["posts"] = {"repository": "posts"}
    config["controllers"]["posts"] = {
        "service": "posts",
        "base_path": "/posts",
        "access": "public",
    }
    return config


def test_minified_controller_expanded_to_routes():
    result = desugar_v02(_config_with_controller())
    ctrl = result["controllers"]["posts"]
    assert "routes" in ctrl
    assert "list" in ctrl["routes"]
    assert ctrl["routes"]["list"]["method"] == "GET"
    assert ctrl["routes"]["list"]["path"] == ""


def test_non_minified_controller_passed_through():
    config = _base_config()
    config["controllers"]["custom"] = {
        "routes": {
            "ping": {
                "service": "svc",
                "method": "GET",
                "path": "/ping",
                "access": "public",
            }
        },
        "base_path": "/custom",
    }
    result = desugar_v02(config)
    assert result["controllers"]["custom"]["routes"]["ping"]["method"] == "GET"


def test_no_matching_services_error():
    config = _base_config()
    config["controllers"]["posts"] = {
        "service": "nonexistent",
        "base_path": "/posts",
        "access": "public",
    }
    with pytest.raises(ConfigErrors) as exc_info:
        desugar_v02(config)
    assert any(e.code == "DESUGAR_SERVICE_NOT_FOUND" for e in exc_info.value.errors)


def test_op_override_false_skips_route():
    config = _config_with_controller()
    config["controllers"]["posts"]["operations"] = {"delete": False}
    result = desugar_v02(config)
    assert "delete" not in result["controllers"]["posts"]["routes"]


def test_standard_crud_ops_correct_method_and_path():
    result = desugar_v02(_config_with_controller())
    routes = result["controllers"]["posts"]["routes"]
    assert routes["list"]["method"] == "GET"
    assert routes["list"]["path"] == ""
    assert routes["get"]["method"] == "GET"
    assert routes["get"]["path"] == "/{id}"
    assert routes["create"]["method"] == "POST"
    assert routes["create"]["path"] == ""
    assert routes["update"]["method"] == "PATCH"
    assert routes["update"]["path"] == "/{id}"
    assert routes["delete"]["method"] == "DELETE"
    assert routes["delete"]["path"] == "/{id}"


def test_custom_op_with_method_and_path():
    config = _config_with_controller()
    config["entities"]["post"] = {"fields": {"id": {"type": "id"}}}
    config["repositories"]["posts"] = {"entity": "post"}
    config["services"]["posts"] = {
        "repository": "posts",
        "operations": {
            "publish": {"handler": "posts.publish"},
        },
    }
    config["controllers"]["posts"]["operations"] = {
        "publish": {"method": "POST", "path": "/{id}/publish"},
    }
    result = desugar_v02(config)
    routes = result["controllers"]["posts"]["routes"]
    assert "publish" in routes
    assert routes["publish"]["method"] == "POST"
    assert routes["publish"]["path"] == "/{id}/publish"


def test_custom_op_without_method_path_error():
    config = _config_with_controller()
    config["entities"]["post"] = {"fields": {"id": {"type": "id"}}}
    config["repositories"]["posts"] = {"entity": "post"}
    config["services"]["posts"] = {
        "repository": "posts",
        "operations": {
            "custom_op": {"handler": "posts.custom"},
        },
    }
    config["controllers"]["posts"]["operations"] = {
        "custom_op": {},
    }
    with pytest.raises(ConfigErrors) as exc_info:
        desugar_v02(config)
    assert any(
        e.code == "DESUGAR_CUSTOM_OP_MISSING_ROUTE" for e in exc_info.value.errors
    )


def test_access_inherited_from_controller_base():
    result = desugar_v02(_config_with_controller())
    routes = result["controllers"]["posts"]["routes"]
    assert routes["list"]["access"] == "public"
    assert routes["create"]["access"] == "public"


def test_access_overridden_per_operation():
    config = _config_with_controller()
    config["controllers"]["posts"]["access"] = "public"
    config["controllers"]["posts"]["operations"] = {
        "create": {"access": "*"},
    }
    result = desugar_v02(config)
    routes = result["controllers"]["posts"]["routes"]
    assert routes["create"]["access"] == "*"
    assert routes["list"]["access"] == "public"


def test_controller_rewritten_service_access_operations_removed():
    result = desugar_v02(_config_with_controller())
    ctrl = result["controllers"]["posts"]
    assert "service" not in ctrl
    assert "access" not in ctrl
    assert "operations" not in ctrl
    assert "routes" in ctrl
