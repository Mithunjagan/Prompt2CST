from __future__ import annotations

from ..design_ir import GeometryOperation
from .common import history_string, resolved


def compile_transform(
    operation: GeometryOperation,
    names: dict[str, str],
    parameters: dict[str, float],
) -> str:
    kind = str(operation.type)
    targets = ",".join(names[target] for target in operation.targets)
    escaped_targets = history_string(targets)
    if kind == "delete":
        return "\n".join(
            f'Solid.Delete "{history_string(names[target])}"'
            for target in operation.targets
        )
    if kind == "rename":
        return f'Solid.Rename "{history_string(names[operation.targets[0]])}", "{history_string(operation.new_name or operation.output or "")}"'

    vector = operation.vector or (0, 0, 0)
    angles = operation.angles or (0, 0, 0)
    center = operation.center
    factor = operation.factor if operation.factor is not None else 1
    repetitions = operation.count or (2 if kind == "duplicate" else 1)
    transform_name = {
        "translate": "Translate",
        "duplicate": "Translate",
        "linear_array": "Translate",
        "rotate": "Rotate",
        "mirror": "Mirror",
        "scale": "Scale",
    }.get(kind)
    if transform_name is None:
        raise ValueError(f"Unsupported transform compiler: transform.{kind}")
    multiple = "True" if kind in {"duplicate", "linear_array"} else "False"
    mirror_vector = {
        "x": ("1", "0", "0"),
        "y": ("0", "1", "0"),
        "z": ("0", "0", "1"),
    }.get(operation.axis or "x")
    return f"""
With Transform
    .Reset
    .Name "{escaped_targets}"
    .Origin "Free"
    .Center "{resolved(center[0], parameters)}", "{resolved(center[1], parameters)}", "{resolved(center[2], parameters)}"
    .Vector "{resolved(vector[0], parameters)}", "{resolved(vector[1], parameters)}", "{resolved(vector[2], parameters)}"
    .Angle "{resolved(angles[0], parameters)}", "{resolved(angles[1], parameters)}", "{resolved(angles[2], parameters)}"
    .PlaneNormal "{mirror_vector[0]}", "{mirror_vector[1]}", "{mirror_vector[2]}"
    .ScaleFactor "{resolved(factor, parameters)}"
    .MultipleObjects "{multiple}"
    .GroupObjects "False"
    .Repetitions "{repetitions}"
    .Transform "Shape", "{transform_name}"
End With
""".strip()
