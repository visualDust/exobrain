"""Mathematical evaluation tool for ExoBrain."""

import ast
import math
import operator
from typing import Any, Callable

from exobrain.tools.base import Tool, ToolParameter


class MathEvaluateTool(Tool):
    """Safely evaluate mathematical expressions."""

    def __init__(self) -> None:
        super().__init__(
            name="math_evaluate",
            description=(
                "Evaluate a mathematical expression safely. Supports arithmetic operators, "
                "parentheses, and common math functions (sin, cos, log, sqrt, etc.). "
                "Use this when exact computation is needed instead of estimating."
            ),
            parameters={
                "expression": ToolParameter(
                    type="string",
                    description=(
                        "The mathematical expression to evaluate. Examples: "
                        "'sin(pi/2) + sqrt(2)', '3*(4+5)**2'."
                    ),
                    required=True,
                ),
                "precision": ToolParameter(
                    type="integer",
                    description="Optional number of decimal places to round the result to.",
                    required=False,
                ),
            },
            requires_permission=False,
        )

        self._allowed_modules = {"math": math}
        self._allowed_names = self._build_allowed_names()
        self._binary_ops: dict[type[ast.AST], Callable[[Any, Any], Any]] = {
            ast.Add: operator.add,
            ast.Sub: operator.sub,
            ast.Mult: operator.mul,
            ast.Div: operator.truediv,
            ast.FloorDiv: operator.floordiv,
            ast.Mod: operator.mod,
            ast.Pow: operator.pow,
        }
        self._unary_ops: dict[type[ast.AST], Callable[[Any], Any]] = {
            ast.UAdd: operator.pos,
            ast.USub: operator.neg,
        }

    def _build_allowed_names(self) -> dict[str, Any]:
        """Collect allowed identifiers from math plus a few builtins."""
        allowed: dict[str, Any] = {"math": math, "abs": abs, "round": round}

        for name in dir(math):
            if name.startswith("_"):
                continue
            value = getattr(math, name)
            if callable(value) or isinstance(value, (int, float, complex)):
                allowed[name] = value

        return allowed

    def _resolve_callable(self, node: ast.AST) -> Callable[..., Any]:
        """Resolve a callable from a Name or Attribute node."""
        if isinstance(node, ast.Name) and node.id in self._allowed_names:
            func = self._allowed_names[node.id]
            if callable(func):
                return func
            raise ValueError(f"'{node.id}' is not callable")

        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            module_name = node.value.id
            module_obj = self._allowed_modules.get(module_name)
            if module_obj is None:
                raise ValueError(f"Unknown module '{module_name}'")
            attr = node.attr
            if attr.startswith("_"):
                raise ValueError("Access to private attributes is not allowed")
            value = getattr(module_obj, attr, None)
            if value is None:
                raise ValueError(f"'{module_name}' has no attribute '{attr}'")
            if callable(value):
                return value
            raise ValueError(f"'{module_name}.{attr}' is not callable")

        raise ValueError("Unsupported function reference")

    def _eval_node(self, node: ast.AST) -> Any:
        """Recursively evaluate an AST node with strict safety checks."""
        if isinstance(node, ast.Expression):
            return self._eval_node(node.body)

        if isinstance(node, ast.Constant):
            if isinstance(node.value, (int, float, complex, bool)):
                return node.value
            raise ValueError("Only numeric constants are allowed")

        if isinstance(node, ast.Name):
            if node.id in self._allowed_names:
                return self._allowed_names[node.id]
            raise ValueError(f"Unknown identifier '{node.id}'")

        if isinstance(node, ast.BinOp):
            op_type = type(node.op)
            if op_type not in self._binary_ops:
                raise ValueError("Operator not allowed")
            left = self._eval_node(node.left)
            right = self._eval_node(node.right)
            return self._binary_ops[op_type](left, right)

        if isinstance(node, ast.UnaryOp):
            op_type = type(node.op)
            if op_type not in self._unary_ops:
                raise ValueError("Operator not allowed")
            operand = self._eval_node(node.operand)
            return self._unary_ops[op_type](operand)

        if isinstance(node, ast.Call):
            func = self._resolve_callable(node.func)
            args = [self._eval_node(arg) for arg in node.args]
            kwargs = {
                kw.arg: self._eval_node(kw.value) for kw in node.keywords if kw.arg is not None
            }
            return func(*args, **kwargs)

        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            module_name = node.value.id
            module_obj = self._allowed_modules.get(module_name)
            if module_obj is None:
                raise ValueError(f"Unknown module '{module_name}'")
            attr = node.attr
            if attr.startswith("_"):
                raise ValueError("Access to private attributes is not allowed")
            value = getattr(module_obj, attr, None)
            if value is None:
                raise ValueError(f"'{module_name}' has no attribute '{attr}'")
            if callable(value) or isinstance(value, (int, float, complex)):
                return value
            raise ValueError(f"'{module_name}.{attr}' is not supported in expressions")

        if isinstance(node, (ast.List, ast.Tuple)):
            return [self._eval_node(elt) for elt in node.elts]

        raise ValueError(f"Unsupported expression element: {type(node).__name__}")

    def _evaluate_expression(self, expression: str) -> Any:
        """Parse and evaluate a mathematical expression safely."""
        try:
            parsed = ast.parse(expression, mode="eval")
        except SyntaxError as exc:
            raise ValueError(f"Invalid expression: {exc}") from exc

        return self._eval_node(parsed)

    async def execute(self, **kwargs: Any) -> str:
        """Execute the math evaluation tool."""
        expression = kwargs.get("expression")
        precision = kwargs.get("precision")

        if not expression or not isinstance(expression, str):
            return "Error: 'expression' must be a non-empty string."

        try:
            result = self._evaluate_expression(expression)
            if precision is not None:
                try:
                    places = int(precision)
                    if places < 0 or places > 15:
                        return "Error: 'precision' must be between 0 and 15."
                except (TypeError, ValueError):
                    return "Error: 'precision' must be an integer."

                if isinstance(result, complex):
                    result = complex(round(result.real, places), round(result.imag, places))
                elif isinstance(result, (float, int)):
                    result = round(result, places)
            return f"Result: {result}"
        except Exception as exc:
            return f"Error evaluating expression: {exc}"
