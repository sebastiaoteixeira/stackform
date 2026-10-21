"""Pydantic building blocks for request payload models."""

from datetime import datetime
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, create_model

from .fields import check_format


SCALAR_TYPES: dict[str, type] = {
    "string": str,
    "id": str,
    "ref": str,
    "number": float,
    "boolean": bool,
    "datetime": datetime,
}
STRICT_TYPES = frozenset({float, bool})
"""Types never coerced from another JSON type."""
CONSTRAINTS = {"minLength": "min_length", "maxLength": "max_length", "min": "ge", "max": "le"}
"""Field config keys and the ``Field`` arguments that enforce them."""


class Payload(BaseModel):
    """A closed object: undeclared keys are rejected."""

    model_config = ConfigDict(extra="forbid")


class OpenPayload(BaseModel):
    """An object that keeps the keys it does not declare."""

    model_config = ConfigDict(extra="allow")


def formatted(format_name: str) -> AfterValidator:
    return AfterValidator(lambda value: check_format(format_name, value))


def partial(model: type[BaseModel], name: str) -> type[BaseModel]:
    """``model`` with every field omittable; types, constraints and nullability are kept."""
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
