"""Build-time expansion of policy references into access-rule when ASTs.

A ``policy:name(args)`` term is a reusable when-fragment. Expansion is pure AST
rewriting performed once at IR-build time: every ``PolicyRef`` inside a rule's
when (and, recursively, inside policy bodies) is replaced by the referenced
policy's when AST. For each policy ``given`` entry and each ``param`` a fresh
unique symbol is minted, its binding is registered into the rule's symbol
tables, and every matching ``FieldRef`` root in the copied body is rewritten to
the fresh name. After this pass an expanded rule contains no ``PolicyRef`` nodes
and is indistinguishable from a hand-written expanded rule.

Param-arg record normalization: when a param's positional arg is a
``request:<entity>`` binding, the fresh symbol is a record-shaped body binding
(``IRRequestBinding(part="body", ...)``) so ``target.<field>`` reads the typed
request body directly; document and identity args keep their usual semantics.
"""

from dataclasses import replace

from yaml_api_generator.ir import (
    And,
    Equals,
    FieldRef,
    In,
    IRAccessRule,
    IRBinding,
    IRDocumentBinding,
    IRIdentityBinding,
    IRPolicy,
    IRRequestBinding,
    Not,
    NotEquals,
    NotIn,
    Or,
    PolicyRef,
    StringLiteral,
    WhenExpr,
)
from yaml_api_generator.ir.when import map_operands
from yaml_api_generator.parsers.yaml_parser import ConfigError
from yaml_api_generator.parsers.transformers.v02.binding_classifier import classify_binding


class _SymbolSink:
    """Accumulates freshly minted bindings into the three symbol tables."""

    def __init__(self) -> None:
        self.identity: dict[str, IRIdentityBinding] = {}
        self.document: dict[str, IRDocumentBinding] = {}
        self.request: dict[str, IRRequestBinding] = {}
        self._counter = 0

    def fresh_name(self, policy_name: str, symbol: str) -> str:
        name = f"_p{self._counter}_{policy_name}__{symbol}"
        self._counter += 1
        return name

    def register(self, name: str, binding: IRBinding) -> None:
        if isinstance(binding, IRIdentityBinding):
            self.identity[name] = binding
        elif isinstance(binding, IRDocumentBinding):
            self.document[name] = binding
        elif isinstance(binding, IRRequestBinding):
            self.request[name] = binding


def _rename_roots(expr: WhenExpr, mapping: dict[str, str]) -> WhenExpr:
    if isinstance(expr, FieldRef):
        return replace(expr, root=mapping.get(expr.root, expr.root))
    return map_operands(expr, lambda child: _rename_roots(child, mapping))


def _normalize_param_binding(binding: IRBinding) -> IRBinding:
    if isinstance(binding, IRRequestBinding):
        return IRRequestBinding(
            part=binding.part or "body", type_name=binding.type_name, raw=binding.raw
        )
    return binding


class PolicyExpander:
    """Recursively expands policy references with acyclic detection."""

    def __init__(
        self,
        policies: dict[str, IRPolicy],
        entity_to_collection: dict[str, str],
    ) -> None:
        self._policies = policies
        self._entity_to_collection = entity_to_collection

    def expand(
        self, expr: WhenExpr | None, sink: _SymbolSink, path: str
    ) -> tuple[WhenExpr | None, list[ConfigError]]:
        if expr is None:
            return None, []
        return self._expand(expr, sink, path, ())

    def _expand(
        self,
        expr: WhenExpr,
        sink: _SymbolSink,
        path: str,
        stack: tuple[str, ...],
    ) -> tuple[WhenExpr, list[ConfigError]]:
        if isinstance(expr, PolicyRef):
            return self._expand_ref(expr, sink, path, stack)
        if isinstance(expr, (Equals, NotEquals, And, Or)):
            left, left_errors = self._expand(expr.left, sink, path, stack)
            right, right_errors = self._expand(expr.right, sink, path, stack)
            return replace(expr, left=left, right=right), left_errors + right_errors
        if isinstance(expr, (In, NotIn)):
            left, errors = self._expand(expr.left, sink, path, stack)
            return replace(expr, left=left), errors
        if isinstance(expr, Not):
            operand, errors = self._expand(expr.operand, sink, path, stack)
            return replace(expr, operand=operand), errors
        return expr, []

    def _expand_ref(
        self,
        ref: PolicyRef,
        sink: _SymbolSink,
        path: str,
        stack: tuple[str, ...],
    ) -> tuple[WhenExpr, list[ConfigError]]:
        policy = self._policies.get(ref.name)
        if policy is None:
            return StringLiteral(value=""), [ConfigError(
                code="POLICY_NOT_FOUND",
                message=f"reference to undefined policy '{ref.name}'",
                path=path,
            )]

        if ref.name in stack:
            cycle = " -> ".join((*stack, ref.name))
            return StringLiteral(value=""), [ConfigError(
                code="POLICY_CYCLE",
                message=f"cyclic policy references: {cycle}",
                path=path,
            )]

        if len(ref.args) != len(policy.params):
            return StringLiteral(value=""), [ConfigError(
                code="POLICY_ARITY_MISMATCH",
                message=(
                    f"policy '{ref.name}' expects {len(policy.params)} "
                    f"arg(s), got {len(ref.args)}"
                ),
                path=path,
            )]

        errors: list[ConfigError] = []
        mapping: dict[str, str] = {}

        for symbol, binding in policy.given.items():
            fresh = sink.fresh_name(ref.name, symbol)
            sink.register(fresh, binding)
            mapping[symbol] = fresh

        for symbol, arg in zip(policy.params, ref.args):
            binding, arg_errors = classify_binding(
                arg, path, self._entity_to_collection
            )
            errors.extend(arg_errors)
            if binding is None:
                continue
            fresh = sink.fresh_name(ref.name, symbol)
            sink.register(fresh, _normalize_param_binding(binding))
            mapping[symbol] = fresh

        if errors:
            return StringLiteral(value=""), errors

        body, body_errors = self._expand(
            policy.when, sink, f"policies.{ref.name}.when", (*stack, ref.name)
        )
        renamed = _rename_roots(body, mapping)
        return renamed, body_errors


def expand_rule_policies(
    rule: IRAccessRule,
    policies: dict[str, IRPolicy],
    entity_to_collection: dict[str, str],
    path: str,
) -> tuple[IRAccessRule, list[ConfigError]]:
    if rule.when is None:
        return rule, []
    sink = _SymbolSink()
    expander = PolicyExpander(policies, entity_to_collection)
    expanded, errors = expander.expand(rule.when, sink, path)
    if errors:
        return rule, errors
    return replace(
        rule,
        when=expanded,
        identity_symbols={**rule.identity_symbols, **sink.identity},
        document_symbols={**rule.document_symbols, **sink.document},
        request_symbols={**rule.request_symbols, **sink.request},
        principal=_rederive_principal(rule, sink),
    ), []


def _rederive_principal(rule: IRAccessRule, sink: _SymbolSink) -> str:
    if rule.principal:
        return rule.principal
    first = next(iter(sink.identity.values()), None)
    return f"identity:{first.collection_name}" if first else ""
