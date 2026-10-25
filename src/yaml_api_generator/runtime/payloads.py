"""Pydantic building blocks for request payload models."""

from copy import deepcopy
from typing import Annotated, Any, ClassVar

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    GetCoreSchemaHandler,
    GetJsonSchemaHandler,
    SerializerFunctionWrapHandler,
    create_model,
    model_serializer,
    model_validator,
)
from pydantic_core import core_schema

from .fields import canonical_datetime, check_format


class Timestamp(str):
    """An ISO 8601 datetime string, stored as its canonical UTC form."""

    @classmethod
    def __get_pydantic_core_schema__(cls, source: Any, handler: GetCoreSchemaHandler) -> core_schema.CoreSchema:
        return core_schema.no_info_after_validator_function(canonical_datetime, core_schema.str_schema())

    @classmethod
    def __get_pydantic_json_schema__(cls, schema: core_schema.CoreSchema, handler: GetJsonSchemaHandler) -> dict[str, Any]:
        return {**handler(schema), "format": "date-time"}


SCALAR_TYPES: dict[str, type] = {
    "string": str,
    "id": str,
    "ref": str,
    "number": float,
    "boolean": bool,
    "datetime": Timestamp,
}
STRICT_TYPES = frozenset({float, bool})
"""Types never coerced from another JSON type."""
CONSTRAINTS = {"minLength": "min_length", "maxLength": "max_length", "min": "ge", "max": "le"}
"""Field config keys and the ``Field`` arguments that enforce them."""


class Payload(BaseModel):
    """A closed object: undeclared and ``_readonly`` keys are rejected.

    A dump leaves out the fields that were neither sent nor given a default;
    ``_server_defaults`` are the defaults of readonly fields, added to every dump.
    """

    model_config = ConfigDict(extra="forbid")
    _readonly: ClassVar[frozenset[str]] = frozenset()
    _server_defaults: ClassVar[dict[str, Any]] = {}

    @model_validator(mode="before")
    @classmethod
    def _reject_readonly(cls, data: Any) -> Any:
        if isinstance(data, dict) and (sent := sorted(cls._readonly & data.keys())):
            raise ValueError(f"Readonly fields: {', '.join(sent)}")
        return data

    @model_serializer(mode="wrap")
    def _dump(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        sent = {
            name: value
            for name, value in handler(self).items()
            if value is not None or name in self.model_fields_set
        }
        return {**sent, **deepcopy(self._server_defaults)}


class OpenPayload(Payload):
    """An object that keeps the keys it does not declare."""

    model_config = ConfigDict(extra="allow")


def formatted(format_name: str) -> AfterValidator:
    return AfterValidator(lambda value: check_format(format_name, value))


def partial(model: type[Payload], name: str) -> type[Payload]:
    """``model`` with every field omittable and no server defaults; types, constraints and nullability are kept."""
    return create_model(
        name,
        __base__=Payload,
        **{
            field_name: (
                Annotated[
                    (info.annotation, *info.metadata, Field(**info.asdict()["attributes"]))
                ],
                None,
            )
            for field_name, info in model.model_fields.items()
        },
    )
