from __future__ import annotations

from ..design_ir import evaluate_expression


def format_number(value: float) -> str:
    return f"{value:.12g}"


def resolved(expression, parameters: dict[str, float]) -> str:
    return format_number(evaluate_expression(expression, parameters))


def object_name(component: str, name: str) -> str:
    return f"{component}:{name}"


def history_string(value: str) -> str:
    return value.replace('"', '""')
