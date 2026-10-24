"""Route building for backend code generation.

Converts IR routes into route descriptors with access control and model references.
"""

import re

from yaml_api_generator.ir import IRDocument, IRDto, IRSymbolRef
from .model_builder import dto_payload_name, payload_name
from ..compile_context import (
    AccessRuleDescriptor,
    DocumentBindingDescriptor,
    ModelDescriptor,
    RequestSymbolDescriptor,
    RouteDescriptor,
)


WRITE_OPERATIONS = ("create", "update", "replace")
DETAIL_OPERATIONS = frozenset({"get", "update", "replace", "delete"})
_REQUEST_PARTS = frozenset({"body", "query", "header", "cookie"})
_PATH_TOKEN = re.compile(r"\{(\w+)\}")


def _base_prefix(document: IRDocument) -> str:
    prefix = document.api.basePath
    if document.api.version:
        prefix = f"{prefix}/{document.api.version}"
    return prefix


def _request_descriptors(rule) -> list[RequestSymbolDescriptor]:
    return [
        RequestSymbolDescriptor(name=name, part=binding.part, type_name=binding.type_name, raw=binding.raw)
        for name, binding in rule.request_symbols.items()
    ]


def _document_descriptors(rule) -> list[DocumentBindingDescriptor]:
    return [
        DocumentBindingDescriptor(
            name=name,
            collection=binding.collection,
            id_param=binding.id_param,
            where={conjunct.field: _rhs_config(conjunct.rhs) for conjunct in binding.where},
        )
        for name, binding in rule.document_symbols.items()
    ]


def _service_config(document: IRDocument, service_name: str | None) -> tuple[
    dict[str, object], dict[str, dict[str, object]]
]:
    service = document.services.get(service_name) if service_name is not None else None
    input_fields = (
        dict(service.input.fields)
        if service is not None and service.input is not None
        else {}
    )
    forwarding = {
        name: _rhs_config(rhs)
        for name, rhs in (service.forwarding.items() if service is not None else ())
    }
    return input_fields, forwarding


def _rhs_config(rhs) -> dict[str, object]:
    if isinstance(rhs, IRSymbolRef):
        return {"symbol": [rhs.root, *rhs.path]}
    return {"literal": rhs.value}


class RouteBuilder:
    """Builds route descriptors from IR routes."""

    def build_routes(
        self,
        document: IRDocument,
        model_index: dict[str, ModelDescriptor],
        dtos: dict[str, IRDto],
    ) -> list[RouteDescriptor]:
        routes: list[RouteDescriptor] = []
        has_identity = bool(document.identityCollections)
        prefix = _base_prefix(document)

        for ir_route in document.routes:
            needs_auth = not ir_route.is_public and has_identity
            relative_path = ir_route.path.removeprefix(prefix) or "/"
            path_params = _PATH_TOKEN.findall(ir_route.path)
            record_id_param, record_parent_params = self._record_params(
                document.version, ir_route.operation, path_params
            )
            service_input, service_forwarding = _service_config(
                document, ir_route.service
            )

            access_rules = None
            if ir_route.access_rules:
                access_rules = [
                    AccessRuleDescriptor(
                        principal=rule.principal,
                        required_role=rule.required_role,
                        identity_symbols=list(rule.identity_symbols.keys()),
                        document_symbols=list(rule.document_symbols.keys()),
                        document_bindings=_document_descriptors(rule),
                        request_symbols=_request_descriptors(rule),
                        when=rule.when,
                        effect=rule.effect,
                        reason=rule.reason if document.version == "0.3" else None,
                        bind={name: _rhs_config(rhs) for name, rhs in rule.bind.items()},
                    )
                    for rule in ir_route.access_rules
                ]

            needs_request = self._needs_request(access_rules)
            body_dto = ir_route.body_dto(dtos)
            typed_body_model = dto_payload_name(body_dto.name, ir_route.operation) if body_dto else None

            if ir_route.handler is not None or ir_route.collection is None:
                routes.append(
                    RouteDescriptor(
                        method=ir_route.method,
                        path=ir_route.path,
                        relative_path=relative_path,
                        operation=ir_route.operation,
                        collection=ir_route.collection,
                        is_public=ir_route.is_public,
                        needs_auth=needs_auth,
                        is_identity_create=False,
                        body_model=None,
                        has_id_param=record_id_param is not None,
                        password_via=False,
                        handler=ir_route.handler,
                        access_rules=access_rules,
                        path_params=path_params,
                        needs_request=needs_request,
                        typed_body_model=typed_body_model,
                        service=ir_route.service,
                        record_id_param=record_id_param,
                        record_parent_params=record_parent_params,
                        service_input=service_input,
                        service_forwarding=service_forwarding,
                    )
                )
                continue

            identity = document.identityCollections.get(ir_route.collection)
            is_identity_create = identity is not None and ir_route.operation == "create"
            uses_password = identity is not None and identity.has_password

            body_model: str | None = None
            if ir_route.operation in WRITE_OPERATIONS or ir_route.operation == "login":
                model_name = payload_name(ir_route.collection, ir_route.operation)
                if model_name in model_index:
                    body_model = model_name

            routes.append(
                RouteDescriptor(
                    method=ir_route.method,
                    path=ir_route.path,
                    relative_path=relative_path,
                    operation=ir_route.operation,
                    collection=ir_route.collection,
                    is_public=ir_route.is_public,
                    needs_auth=needs_auth,
                    is_identity_create=is_identity_create,
                    body_model=body_model,
                    has_id_param=record_id_param is not None,
                    password_via=uses_password,
                    access_rules=access_rules,
                    path_params=path_params,
                    needs_request=needs_request,
                    typed_body_model=typed_body_model,
                    service=ir_route.service,
                    record_id_param=record_id_param,
                    record_parent_params=record_parent_params,
                    id_field=document.collections[ir_route.collection].idField,
                    service_input=service_input,
                    service_forwarding=service_forwarding,
                    pagination=ir_route.pagination,
                )
            )

        return routes

    @staticmethod
    def _record_params(
        spec_version: str, operation: str, path_params: list[str]
    ) -> tuple[str | None, list[str]]:
        if operation not in DETAIL_OPERATIONS:
            return None, []
        if spec_version == "0.3" and path_params:
            return path_params[-1], path_params[:-1]
        return ("id", []) if "id" in path_params else (None, [])

    @staticmethod
    def _needs_request(rules: list[AccessRuleDescriptor] | None) -> bool:
        return any(
            sym.binds(part)
            for rule in rules or ()
            for sym in rule.request_symbols
            for part in _REQUEST_PARTS
        )
