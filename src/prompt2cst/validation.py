from __future__ import annotations

import math
import os
from dataclasses import asdict, dataclass
from enum import StrEnum

from .capabilities import unsupported_for_design
from .design_ir import (
    Brick,
    Cone,
    Cylinder,
    DesignIR,
    GeometryOperation,
    MaterialKind,
    PolygonExtrusion,
    Sphere,
    evaluate_expression,
    resolve_parameters,
)


class Severity(StrEnum):
    INFO = "INFO"
    WARNING = "WARNING"
    BLOCKING_ERROR = "BLOCKING_ERROR"


@dataclass(frozen=True)
class ValidationFinding:
    severity: Severity
    category: str
    code: str
    message: str
    object_id: str | None = None

    def to_dict(self) -> dict:
        result = asdict(self)
        result["severity"] = self.severity.value
        return result


@dataclass
class ValidationReport:
    findings: list[ValidationFinding]
    resolved_parameters: dict[str, float]
    estimated_mesh_cells: int | None
    sweep_case_count: int

    @property
    def blocking(self) -> bool:
        return any(item.severity == Severity.BLOCKING_ERROR for item in self.findings)

    def to_dict(self) -> dict:
        return {
            "valid": not self.blocking,
            "blocking": self.blocking,
            "findings": [item.to_dict() for item in self.findings],
            "resolved_parameters": self.resolved_parameters,
            "estimated_mesh_cells": self.estimated_mesh_cells,
            "sweep_case_count": self.sweep_case_count,
        }


BBox = tuple[float, float, float, float, float, float]


def validate_design(design: DesignIR) -> ValidationReport:
    findings: list[ValidationFinding] = []
    try:
        parameters = resolve_parameters(design)
    except ValueError as exc:
        findings.append(_error("schema", "expression.invalid", str(exc)))
        parameters = {}

    geometry_by_id = {item.id: item for item in design.geometry}
    all_ids = {
        *geometry_by_id,
        *(item.id for item in design.operations),
        *(item.id for item in design.excitations),
        *(item.id for item in design.monitors),
    }
    _validate_dependencies(design, all_ids, findings)
    _validate_operation_order(design.operations, findings)

    boxes: dict[str, BBox] = {}
    for item in design.geometry:
        try:
            box = geometry_bbox(item, parameters)
            if box is not None:
                boxes[item.id] = box
                if _bbox_volume(box) <= 0 and not item.type.startswith(
                    ("sheet", "polygon", "curve", "polyline")
                ):
                    findings.append(
                        _error(
                            "geometry",
                            "geometry.zero_volume",
                            "Solid has zero volume.",
                            item.id,
                        )
                    )
        except (ValueError, ZeroDivisionError, OverflowError) as exc:
            findings.append(
                _error("geometry", "geometry.invalid_dimension", str(exc), item.id)
            )

    material_by_id = {item.id: item for item in design.materials}
    for item in design.geometry:
        if not item.material:
            findings.append(
                _error(
                    "material",
                    "material.missing",
                    "Geometry object has no material.",
                    item.id,
                )
            )
        elif item.material != "PEC" and item.material not in material_by_id:
            findings.append(
                _error(
                    "material",
                    "material.undefined",
                    f"Undefined material: {item.material}",
                    item.id,
                )
            )
    for material in design.materials:
        if (
            material.kind == MaterialKind.CONDUCTOR
            and material.conductivity_s_per_m is None
        ):
            findings.append(
                _error(
                    "material",
                    "material.conductivity_missing",
                    "Conductor requires conductivity_s_per_m.",
                    material.id,
                )
            )

    for operation in sorted(
        design.operations, key=lambda item: (item.operation_order, item.id)
    ):
        missing_targets = [
            target for target in operation.targets if target not in geometry_by_id
        ]
        if missing_targets:
            findings.append(
                _error(
                    "dependency",
                    "operation.target_missing",
                    f"Missing operation targets: {', '.join(missing_targets)}",
                    operation.id,
                )
            )
            continue
        if (
            operation.type in {"union", "subtract", "intersect"}
            and len(operation.targets) < 2
        ):
            findings.append(
                _error(
                    "geometry",
                    "boolean.targets",
                    "Boolean operation requires at least two targets.",
                    operation.id,
                )
            )
            continue
        if operation.type == "union":
            if not _all_connected([boxes.get(target) for target in operation.targets]):
                findings.append(
                    _warning(
                        "geometry",
                        "union.non_touching",
                        "Union targets do not touch or overlap.",
                        operation.id,
                    )
                )
        elif operation.type in {"subtract", "intersect"}:
            target_box = boxes.get(operation.targets[0])
            for tool in operation.targets[1:]:
                if not _overlap(target_box, boxes.get(tool)):
                    findings.append(
                        _error(
                            "geometry",
                            f"{operation.type}.no_intersection",
                            f"{operation.type.title()} tool {tool} does not intersect its target.",
                            operation.id,
                        )
                    )
        elif (
            operation.type in {"translate", "duplicate", "linear_array"}
            and operation.vector is None
        ):
            findings.append(
                _error(
                    "geometry",
                    "transform.vector_missing",
                    "Transform requires a vector.",
                    operation.id,
                )
            )
        elif operation.type == "rotate" and operation.angles is None:
            findings.append(
                _error(
                    "geometry",
                    "transform.angles_missing",
                    "Rotation requires angles.",
                    operation.id,
                )
            )
        elif operation.type == "scale":
            if operation.factor is None:
                findings.append(
                    _error(
                        "geometry",
                        "transform.factor_missing",
                        "Scale requires a factor.",
                        operation.id,
                    )
                )
            else:
                try:
                    if evaluate_expression(operation.factor, parameters) <= 0:
                        raise ValueError("scale factor must be positive")
                except ValueError as exc:
                    findings.append(
                        _error(
                            "geometry",
                            "transform.factor_invalid",
                            str(exc),
                            operation.id,
                        )
                    )

    conductor_ids = {
        item.id
        for item in design.geometry
        if item.material == "PEC"
        or (
            item.material in material_by_id
            and material_by_id[item.material].kind
            in {MaterialKind.PEC, MaterialKind.CONDUCTOR}
        )
    }
    for port in design.excitations:
        if port.type == "waveguide_port":
            continue
        try:
            p1 = _point(port.p1, parameters)
            p2 = _point(port.p2, parameters)
        except ValueError as exc:
            findings.append(
                _error("port", "port.expression_invalid", str(exc), port.id)
            )
            continue
        if p1 == p2:
            findings.append(
                _error(
                    "port", "port.degenerate", "Port endpoints must differ.", port.id
                )
            )
        touching1 = {
            item for item in conductor_ids if _point_touches_bbox(p1, boxes.get(item))
        }
        touching2 = {
            item for item in conductor_ids if _point_touches_bbox(p2, boxes.get(item))
        }
        if port.negative_conductor and port.negative_conductor not in touching1:
            findings.append(
                _error(
                    "port",
                    "port.negative_not_touching",
                    "P1 does not touch the declared negative conductor.",
                    port.id,
                )
            )
        if port.positive_conductor and port.positive_conductor not in touching2:
            findings.append(
                _error(
                    "port",
                    "port.positive_not_touching",
                    "P2 does not touch the declared positive conductor.",
                    port.id,
                )
            )
        if not touching1 or not touching2:
            findings.append(
                _error(
                    "port",
                    "port.endpoint_not_touching",
                    "Each discrete-port endpoint must touch a conductor.",
                    port.id,
                )
            )
        if touching1 & touching2:
            findings.append(
                _error(
                    "port",
                    "port.unintended_short",
                    "Both endpoints touch the same conductor.",
                    port.id,
                )
            )

    if design.solver:
        try:
            fmin = evaluate_expression(design.solver.frequency_min, parameters)
            fmax = evaluate_expression(design.solver.frequency_max, parameters)
            if fmin <= 0 or fmax <= fmin:
                raise ValueError("solver frequency range must satisfy 0 < min < max")
            for monitor in design.monitors:
                frequency = evaluate_expression(monitor.frequency, parameters)
                if not fmin <= frequency <= fmax:
                    findings.append(
                        _error(
                            "simulation",
                            "monitor.outside_range",
                            f"Monitor frequency {frequency:g} is outside {fmin:g} to {fmax:g}.",
                            monitor.id,
                        )
                    )
        except ValueError as exc:
            findings.append(_error("simulation", "solver.frequency_invalid", str(exc)))
    elif design.monitors or design.excitations:
        findings.append(
            _error(
                "simulation",
                "solver.missing",
                "Ports or monitors require a solver configuration.",
            )
        )

    if design.solver and design.boundaries is None:
        findings.append(
            _error(
                "simulation",
                "boundary.missing",
                "Solver configuration requires complete boundary conditions.",
            )
        )

    for missing in unsupported_for_design(design):
        message = f"Unsupported requested capability: {missing['id']}."
        if missing.get("closest_alternative"):
            message += (
                f" Closest supported alternative: {missing['closest_alternative']}."
            )
        message += (
            " A deterministic compiler extension can add it."
            if missing.get("extensible")
            else ""
        )
        findings.append(
            _error("capability", "capability.unsupported", message, missing["id"])
        )

    sweep_cases = 1
    for sweep in design.parameter_sweeps:
        count = sweep.case_count()
        if sweep.parameter not in design.parameters:
            findings.append(
                _error(
                    "sweep",
                    "sweep.parameter_missing",
                    f"Sweep parameter {sweep.parameter} is undefined.",
                    sweep.id,
                )
            )
        if count <= 0:
            findings.append(
                _error(
                    "sweep",
                    "sweep.range_invalid",
                    "Sweep has no valid cases.",
                    sweep.id,
                )
            )
        else:
            sweep_cases *= count
    max_cases = int(os.getenv("PROMPT2CST_MAX_SWEEP_CASES", "200"))
    if sweep_cases > max_cases:
        findings.append(
            _error(
                "sweep",
                "sweep.too_many_cases",
                f"Sweep expands to {sweep_cases} cases; limit is {max_cases}.",
            )
        )

    estimated_mesh = design.mesh.estimated_cells if design.mesh else None
    max_mesh = int(os.getenv("PROMPT2CST_MAX_ESTIMATED_MESH_CELLS", "100000"))
    if estimated_mesh and estimated_mesh > max_mesh:
        findings.append(
            _error(
                "mesh",
                "mesh.licence_limit",
                f"Estimated mesh {estimated_mesh} exceeds configured limit {max_mesh}.",
            )
        )

    if not findings:
        findings.append(
            ValidationFinding(
                Severity.INFO,
                "validation",
                "validation.ok",
                "Deterministic validation passed.",
            )
        )
    return ValidationReport(findings, parameters, estimated_mesh, sweep_cases)


def geometry_bbox(item, parameters: dict[str, float]) -> BBox | None:
    def value(expression):
        return evaluate_expression(expression, parameters)

    if isinstance(item, Brick):
        return _ordered_box(
            value(item.x[0]),
            value(item.x[1]),
            value(item.y[0]),
            value(item.y[1]),
            value(item.z[0]),
            value(item.z[1]),
        )
    if isinstance(item, Cylinder):
        start, stop = value(item.axis_range[0]), value(item.axis_range[1])
        outer, inner = value(item.outer_radius), value(item.inner_radius)
        if outer <= 0 or inner < 0 or inner >= outer:
            raise ValueError("cylinder radii must satisfy 0 <= inner < outer")
        u, v = value(item.center[0]), value(item.center[1])
        if item.axis == "x":
            return _ordered_box(start, stop, u - outer, u + outer, v - outer, v + outer)
        if item.axis == "y":
            return _ordered_box(u - outer, u + outer, start, stop, v - outer, v + outer)
        return _ordered_box(u - outer, u + outer, v - outer, v + outer, start, stop)
    if isinstance(item, Sphere):
        center = _point(item.center, parameters)
        radius = value(item.radius)
        if radius <= 0:
            raise ValueError("sphere radius must be positive")
        return (
            center[0] - radius,
            center[0] + radius,
            center[1] - radius,
            center[1] + radius,
            center[2] - radius,
            center[2] + radius,
        )
    if isinstance(item, Cone):
        start, stop = value(item.axis_range[0]), value(item.axis_range[1])
        radius = max(value(item.radius1), value(item.radius2))
        if radius < 0 or start >= stop:
            raise ValueError("cone ranges and radii are invalid")
        u, v = value(item.center[0]), value(item.center[1])
        if item.axis == "x":
            return (start, stop, u - radius, u + radius, v - radius, v + radius)
        if item.axis == "y":
            return (u - radius, u + radius, start, stop, v - radius, v + radius)
        return (u - radius, u + radius, v - radius, v + radius, start, stop)
    if isinstance(item, PolygonExtrusion):
        points = [(value(x), value(y)) for x, y in item.points]
        start, stop = value(item.range[0]), value(item.range[1])
        if start >= stop:
            raise ValueError("extrusion range must be increasing")
        xs, ys = zip(*points)
        if item.plane == "xy":
            return (min(xs), max(xs), min(ys), max(ys), start, stop)
        if item.plane == "xz":
            return (min(xs), max(xs), start, stop, min(ys), max(ys))
        return (start, stop, min(xs), max(xs), min(ys), max(ys))
    return None


def _validate_dependencies(
    design: DesignIR, all_ids: set[str], findings: list[ValidationFinding]
) -> None:
    graph: dict[str, list[str]] = {}
    for item in [*design.geometry, *design.operations, *design.excitations]:
        dependencies = list(item.dependencies)
        graph[item.id] = dependencies
        missing = [
            dependency for dependency in dependencies if dependency not in all_ids
        ]
        if missing:
            findings.append(
                _error(
                    "dependency",
                    "dependency.missing",
                    f"Missing dependencies: {', '.join(missing)}",
                    item.id,
                )
            )
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node: str) -> bool:
        if node in visiting:
            return True
        if node in visited:
            return False
        visiting.add(node)
        if any(visit(child) for child in graph.get(node, []) if child in graph):
            return True
        visiting.remove(node)
        visited.add(node)
        return False

    for node in graph:
        if visit(node):
            findings.append(
                _error(
                    "dependency", "dependency.cycle", "Dependency cycle detected.", node
                )
            )
            break


def _validate_operation_order(
    operations: list[GeometryOperation], findings: list[ValidationFinding]
) -> None:
    orders = [item.operation_order for item in operations]
    if len(orders) != len(set(orders)):
        findings.append(
            _error(
                "dependency",
                "operation.order_duplicate",
                "Operation order values must be unique.",
            )
        )


def _ordered_box(x1, x2, y1, y2, z1, z2) -> BBox:
    if not (x1 < x2 and y1 < y2 and z1 < z2):
        raise ValueError("solid coordinate ranges must be strictly increasing")
    if any(
        not math.isfinite(value) or abs(value) > 1e7
        for value in (x1, x2, y1, y2, z1, z2)
    ):
        raise ValueError("geometry coordinates must be finite and within limits")
    return (x1, x2, y1, y2, z1, z2)


def _bbox_volume(box: BBox) -> float:
    return (box[1] - box[0]) * (box[3] - box[2]) * (box[5] - box[4])


def _overlap(first: BBox | None, second: BBox | None, tolerance: float = 1e-9) -> bool:
    if first is None or second is None:
        return False
    return all(
        first[axis * 2] <= second[axis * 2 + 1] + tolerance
        and second[axis * 2] <= first[axis * 2 + 1] + tolerance
        for axis in range(3)
    )


def _all_connected(boxes: list[BBox | None]) -> bool:
    if not boxes or any(box is None for box in boxes):
        return False
    connected = {0}
    while True:
        added = {
            index
            for index, box in enumerate(boxes)
            if index not in connected
            and any(_overlap(box, boxes[other]) for other in connected)
        }
        if not added:
            return len(connected) == len(boxes)
        connected.update(added)


def _point(point, parameters) -> tuple[float, float, float]:
    return tuple(evaluate_expression(value, parameters) for value in point)


def _point_touches_bbox(
    point: tuple[float, float, float], box: BBox | None, tolerance: float = 1e-6
) -> bool:
    if box is None:
        return False
    return all(
        box[axis * 2] - tolerance <= point[axis] <= box[axis * 2 + 1] + tolerance
        for axis in range(3)
    )


def _error(
    category: str, code: str, message: str, object_id: str | None = None
) -> ValidationFinding:
    return ValidationFinding(
        Severity.BLOCKING_ERROR, category, code, message, object_id
    )


def _warning(
    category: str, code: str, message: str, object_id: str | None = None
) -> ValidationFinding:
    return ValidationFinding(Severity.WARNING, category, code, message, object_id)
