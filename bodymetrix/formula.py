"""Evaluate user-defined fat percentage formulas from two mm readings."""

from __future__ import annotations

import ast
import math
import re
from dataclasses import dataclass
from typing import Any


ALLOWED_NAMES = {"mm1", "mm2", "math", "abs", "min", "max", "pow", "sqrt", "round"}
ALLOWED_NODES = (
    ast.Expression,
    ast.BinOp,
    ast.UnaryOp,
    ast.Constant,
    ast.Name,
    ast.Load,
    ast.Add,
    ast.Sub,
    ast.Mult,
    ast.Div,
    ast.Pow,
    ast.Mod,
    ast.USub,
    ast.UAdd,
    ast.Call,
    ast.Attribute,
)


@dataclass(frozen=True)
class FormulaResult:
    fat_percent: float
    expression: str


class FormulaError(ValueError):
    pass


def _validate_ast(node: ast.AST) -> None:
    if not isinstance(node, ALLOWED_NODES):
        raise FormulaError(f"Unsupported expression element: {type(node).__name__}")
    for child in ast.iter_child_nodes(node):
        if isinstance(child, ast.Name) and child.id not in ALLOWED_NAMES:
            raise FormulaError(f"Unknown variable or function: {child.id}")
        if isinstance(child, ast.Attribute):
            if not (
                isinstance(child.value, ast.Name)
                and child.value.id == "math"
                and child.attr in dir(math)
            ):
                raise FormulaError(f"Unsupported attribute access: {child.attr}")
        _validate_ast(child)


def compile_formula(expression: str) -> ast.Expression:
    expression = expression.strip()
    if not expression or expression == "REPLACE_WITH_YOUR_FORMULA":
        raise FormulaError(
            "Set your fat percentage formula in config.json "
            "(copy config.example.json and edit fat_percent_formula)."
        )
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise FormulaError(f"Invalid formula syntax: {exc}") from exc
    _validate_ast(tree)
    return tree


def evaluate_edwards_bodyfat(thigh: float, waist: float, sex: str) -> FormulaResult:
    """Scanoprobe-era Edwards 2-site formula (thigh mm, waist mm, sex)."""
    if thigh <= 0 or waist <= 0:
        raise FormulaError("Thigh and waist mm must be greater than zero.")
    sex_norm = sex.lower().strip()
    if sex_norm in ("f", "female"):
        log10_thigh = math.log10(thigh)
        log10_waist = math.log10(waist)
        d = 1.12 - 0.0365 * log10_thigh - 0.0389 * log10_waist
        rpf = 100 * (4.57 / d - 4.142)
        pf = rpf
        if rpf > 1.099:
            pf = rpf - 4
        if rpf > 15.099:
            pf = rpf - 3.5
        if rpf > 20.099:
            pf = rpf - 2.5
        if rpf > 25.099:
            pf = rpf - 2
        if rpf > 29.099:
            pf = rpf - 1
        if rpf > 33.099:
            pf = rpf - 0.5
        if rpf > 36.099:
            pf = rpf + 2
    elif sex_norm in ("m", "male"):
        d = 1.107 - 0.003845 * thigh - 0.001493 * waist
        pf = 100 * (4.57 / d - 4.142)
    else:
        raise FormulaError("Sex must be female or male.")

    if not math.isfinite(pf):
        raise FormulaError("Formula produced a non-finite result.")
    return FormulaResult(fat_percent=round(pf, 2), expression="edwards_2site")


def evaluate_fat_percent(expression: str, mm1: float, mm2: float) -> FormulaResult:
    if mm1 <= 0 or mm2 <= 0:
        raise FormulaError("Both mm readings must be greater than zero.")
    tree = compile_formula(expression)
    env: dict[str, Any] = {"mm1": mm1, "mm2": mm2, "math": math}
    value = eval(compile(tree, "<formula>", "eval"), {"__builtins__": {}}, env)  # noqa: S307
    if not isinstance(value, (int, float)):
        raise FormulaError("Formula must evaluate to a number.")
    if not math.isfinite(value):
        raise FormulaError("Formula produced a non-finite result.")
    return FormulaResult(fat_percent=float(value), expression=expression)


def default_placeholder_formula() -> str:
    """Linear placeholder — replace with your validated equation."""
    return "4.57 + 0.28 * mm1 + 0.31 * mm2"
