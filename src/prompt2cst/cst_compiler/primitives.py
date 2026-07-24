from __future__ import annotations

from ..design_ir import Brick, Cylinder
from .common import history_string, resolved


def compile_primitive(item, parameters: dict[str, float]) -> str:
    if isinstance(item, Brick):
        return f"""
With Brick
    .Reset
    .Name "{history_string(item.name)}"
    .Component "{history_string(item.component)}"
    .Material "{history_string(item.material or "")}"
    .Xrange "{resolved(item.x[0], parameters)}", "{resolved(item.x[1], parameters)}"
    .Yrange "{resolved(item.y[0], parameters)}", "{resolved(item.y[1], parameters)}"
    .Zrange "{resolved(item.z[0], parameters)}", "{resolved(item.z[1], parameters)}"
    .Create
End With
""".strip()
    if isinstance(item, Cylinder):
        range_method = {"x": "Xrange", "y": "Yrange", "z": "Zrange"}[item.axis]
        centers = {
            "x": ("Ycenter", "Zcenter"),
            "y": ("Xcenter", "Zcenter"),
            "z": ("Xcenter", "Ycenter"),
        }[item.axis]
        return f"""
With Cylinder
    .Reset
    .Name "{history_string(item.name)}"
    .Component "{history_string(item.component)}"
    .Material "{history_string(item.material or "")}"
    .OuterRadius "{resolved(item.outer_radius, parameters)}"
    .InnerRadius "{resolved(item.inner_radius, parameters)}"
    .Axis "{item.axis}"
    .{range_method} "{resolved(item.axis_range[0], parameters)}", "{resolved(item.axis_range[1], parameters)}"
    .{centers[0]} "{resolved(item.center[0], parameters)}"
    .{centers[1]} "{resolved(item.center[1], parameters)}"
    .Segments "0"
    .Create
End With
""".strip()
    raise ValueError(f"Unsupported primitive compiler: geometry.{item.type}")
