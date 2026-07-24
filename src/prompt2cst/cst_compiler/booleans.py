from __future__ import annotations

from ..design_ir import GeometryOperation
from .common import history_string


def compile_boolean(operation: GeometryOperation, names: dict[str, str]) -> str:
    method = {
        "union": "Add",
        "subtract": "Subtract",
        "intersect": "Intersect",
    }[str(operation.type)]
    target = history_string(names[operation.targets[0]])
    blocks = []
    for tool_id in operation.targets[1:]:
        tool = history_string(names[tool_id])
        blocks.append(f'Solid.{method} "{target}", "{tool}"')
    return "\n".join(blocks)
