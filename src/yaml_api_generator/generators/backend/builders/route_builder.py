"""Route building for backend code generation.

Converts IR routes into route descriptors with access control and model references.
"""

from yaml_api_generator.ir import IRDocument
from ..compile_context import AccessRuleDescriptor, ModelDescriptor, RouteDescriptor


WRITE_OPERATIONS = ("create", "update", "replace")


class RouteBuilder:
    """Builds route descriptors from IR routes."""

    def build_routes(
        self,
        document: IRDocument,
        model_index: dict[str, ModelDescriptor],
    ) -> list[RouteDescriptor]:
        """Build route descriptors from IR.

        Args:
            document: Complete IR document
            model_index: Index of model descriptors by name

        Returns:
            List of route descriptors
        """
        routes: list[RouteDescriptor] = []
        has_identity = bool(document.identityCollections)

        for ir_route in document.routes:
            needs_auth = not ir_route.is_public and has_identity

            access_rules = None
            if ir_route.access_rules:
                access_rules = [
                    AccessRuleDescriptor(
                        principal=rule.principal,
                        required_role=rule.required_role,
                        identity_symbols=list(rule.identity_symbols.keys()),
                        document_symbols=list(rule.document_symbols.keys()),
                        when=rule.when,
                        effect=rule.effect,
                    )
                    for rule in ir_route.access_rules
                ]

            if ir_route.handler is not None or ir_route.collection is None:
                routes.append(
                    RouteDescriptor(
                        method=ir_route.method,
                        path=ir_route.path,
                        operation=ir_route.operation,
                        collection=ir_route.collection,
                        is_public=ir_route.is_public,
                        needs_auth=needs_auth,
                        is_identity_create=False,
                        body_model=None,
                        has_id_param="{id}" in ir_route.path,
                        password_via=False,
                        handler=ir_route.handler,
                        access_rules=access_rules,
                    )
                )
                continue

            col = document.collections[ir_route.collection]
            identity = document.identityCollections.get(ir_route.collection)
            is_identity_create = identity is not None and ir_route.operation == "create"
            uses_password = identity is not None and identity.has_password

            body_model: str | None = None
            if ir_route.operation in WRITE_OPERATIONS or ir_route.operation == "login":
                model_name = self._model_name(ir_route.collection, ir_route.operation)
                if model_name in model_index:
                    body_model = model_name

            routes.append(
                RouteDescriptor(
                    method=ir_route.method,
                    path=ir_route.path,
                    operation=ir_route.operation,
                    collection=ir_route.collection,
                    is_public=ir_route.is_public,
                    needs_auth=needs_auth,
                    is_identity_create=is_identity_create,
                    body_model=body_model,
                    has_id_param="{id}" in ir_route.path,
                    password_via=uses_password,
                    access_rules=access_rules,
                )
            )

        return routes

    def _model_name(self, collection: str, operation: str) -> str:
        col_part = "".join(part.capitalize() for part in collection.split("_"))
        return f"{col_part}{operation.capitalize()}Payload"
