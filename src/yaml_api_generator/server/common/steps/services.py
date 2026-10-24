"""Service ``input:`` validation and ``with:`` forwarding pipeline step.

A service declares the named inputs it requires; they are drawn from the request
(path parameters and body) and validated against their declared types before the
service runs, so a bad input aborts with 422 and the downstream repository or
handler never executes. The service's ``with:`` map is then resolved against the
validated inputs -- each right-hand-side ``$symbol`` names an input field, or is a
literal -- into a forwarding namespace exposed on the context. Repository
operations read it through the request parameters; handlers read it from
``ctx.service_inputs``.
"""

from typing import Any

from yaml_api_generator.ir import IRSymbolRef, WhereRhs
from yaml_api_generator.runtime.fields import conform_inputs

from ..request_context import RequestContext
from . import Step


def ServiceInputStep(
    input_fields: dict[str, dict[str, Any]],
    forwarding: dict[str, WhereRhs],
) -> Step:
    def step(ctx: RequestContext) -> RequestContext:
        inputs = conform_inputs(input_fields, _request_namespace(ctx))
        forwarded = {
            name: _resolve(rhs, inputs) for name, rhs in forwarding.items()
        }
        ctx.service_inputs = forwarded
        return ctx

    return step


def _request_namespace(ctx: RequestContext) -> dict[str, Any]:
    body = ctx.body if isinstance(ctx.body, dict) else {}
    return {**body, **ctx.url_params, **(ctx.bound_inputs or {})}


def _resolve(rhs: WhereRhs, inputs: dict[str, Any]) -> Any:
    if isinstance(rhs, IRSymbolRef):
        value: Any = inputs.get(rhs.root)
        for segment in rhs.path:
            if not isinstance(value, dict):
                return None
            value = value.get(segment)
        return value
    return rhs.value
