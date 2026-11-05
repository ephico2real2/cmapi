"""The small expression language of approval-rules.yaml `when:` lines.

    quotaIncreasePct > 100
    capacity == "warn"
    action == "delete" and reason != "expired" and (namespaceAgeDays > 90 or pods > 20)

Parsed once at load with Python's ast and a whitelist: names (facts), string, number and bool
constants, comparisons, and/or/not, in/not in over literal lists. Anything else (calls,
attributes, subscripts, arithmetic) is refused at load. An unknown fact name is refused at load;
a known fact that is absent at evaluation is None. == and != compare it normally (a missing
reason is != "expired"); <, >, <=, >=, in and not in with None are unknown, and unknown stays
unknown through not, and, or (three-valued, as in SQL). A line whose result is unknown is false, so
a missing number never adds or waives an approval, with or without `not`.
"""
from __future__ import annotations

import ast
import operator
from typing import Any, Mapping

_CMP = {ast.Eq: operator.eq, ast.NotEq: operator.ne, ast.Gt: operator.gt, ast.GtE: operator.ge,
        ast.Lt: operator.lt, ast.LtE: operator.le,
        ast.In: lambda a, b: a in b, ast.NotIn: lambda a, b: a not in b}

# Every fact a planner may put on a request. Adding one here is a code change, on purpose.
KNOWN_FACTS = frozenset({
    "plugin", "action", "environment", "reason", "namespace", "clusterId", "team", "tier",
    "tierChange", "quotaIncreasePct", "requestToPeakRatio", "capacity", "capacityFresh",
    "quotaBelowRequested", "namespaceAgeDays", "pods", "pvcs", "keyClasses",
    "expirationAction", "expirationBeyondLimits",
    "sensitiveKeyChanged", "warnings", "clusterRoles", "requesterClient", "protected", "automated",
})


class ExpressionError(ValueError):
    pass


class Expression:
    def __init__(self, source: str, known: frozenset[str] = KNOWN_FACTS):
        self.source = source
        try:
            tree = ast.parse(source, mode="eval")
        except SyntaxError as exc:
            raise ExpressionError(f"{source!r}: {exc.msg}") from exc
        self._check(tree.body, known)
        self._tree = tree.body

    def _check(self, node: ast.AST, known: frozenset[str]) -> None:
        if isinstance(node, ast.BoolOp):
            for v in node.values:
                self._check(v, known)
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            self._check(node.operand, known)
        elif isinstance(node, ast.Compare):
            if not all(type(op) in _CMP for op in node.ops):
                raise ExpressionError(f"{self.source!r}: unsupported comparison")
            for v in [node.left, *node.comparators]:
                self._check(v, known)
        elif isinstance(node, ast.Name):
            if node.id not in known:
                raise ExpressionError(f"{self.source!r}: unknown fact {node.id}")
        elif isinstance(node, ast.Constant):
            if not isinstance(node.value, (str, int, float, bool)) and node.value is not None:
                raise ExpressionError(f"{self.source!r}: unsupported constant")
        elif isinstance(node, (ast.List, ast.Tuple)):
            for v in node.elts:
                if not isinstance(v, ast.Constant):
                    raise ExpressionError(f"{self.source!r}: lists hold constants only")
        else:
            raise ExpressionError(f"{self.source!r}: {type(node).__name__} is not allowed")

    def __call__(self, facts: Mapping[str, Any]) -> bool:
        return self._eval(self._tree, facts) is True

    def _eval(self, node: ast.AST, facts: Mapping[str, Any]) -> Any:
        if isinstance(node, ast.BoolOp):
            vals = [self._truth(self._eval(v, facts)) for v in node.values]
            if isinstance(node.op, ast.And):
                return False if False in vals else (None if None in vals else True)
            return True if True in vals else (None if None in vals else False)
        if isinstance(node, ast.UnaryOp):
            v = self._truth(self._eval(node.operand, facts))
            return None if v is None else not v
        if isinstance(node, ast.Compare):
            left = self._eval(node.left, facts)
            for op, right_node in zip(node.ops, node.comparators):
                right = self._eval(right_node, facts)
                if (left is None or right is None) and not isinstance(op, (ast.Eq, ast.NotEq)):
                    return None
                try:
                    if not _CMP[type(op)](left, right):
                        return False
                except TypeError:
                    return None
                left = right
            return True
        if isinstance(node, ast.Name):
            return facts.get(node.id)
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, (ast.List, ast.Tuple)):
            return [e.value for e in node.elts]   # type: ignore[attr-defined]
        raise ExpressionError(f"cannot evaluate {type(node).__name__}")

    @staticmethod
    def _truth(v: Any) -> bool | None:
        return None if v is None else bool(v)

    def names(self) -> set[str]:
        return {n.id for n in ast.walk(self._tree) if isinstance(n, ast.Name)}
