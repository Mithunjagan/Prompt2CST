from __future__ import annotations

import ast
import math
import re
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

ID_PATTERN = r"^[A-Za-z][A-Za-z0-9_-]{0,63}$"
Expression = float | int | str
Point3D = tuple[Expression, Expression, Expression]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Units(StrictModel):
    length: Literal["mm", "cm", "m", "um"] = "mm"
    frequency: Literal["Hz", "kHz", "MHz", "GHz"] = "GHz"
    time: Literal["s", "ms", "us", "ns"] = "ns"


class ProjectMetadata(StrictModel):
    name: str = Field(min_length=1, max_length=80)
    description: str = Field(default="", max_length=1000)
    requested_topology: str = Field(default="", max_length=120)
    author: str = Field(default="Prompt2CST", max_length=80)


class Parameter(StrictModel):
    value: Expression
    unit: str = Field(default="", max_length=16)
    description: str = Field(default="", max_length=240)
    minimum: float | None = None
    maximum: float | None = None

    @model_validator(mode="after")
    def validate_bounds(self):
        if (
            self.minimum is not None
            and self.maximum is not None
            and self.minimum > self.maximum
        ):
            raise ValueError("parameter minimum must not exceed maximum")
        return self


class MaterialKind(StrEnum):
    PEC = "pec"
    CONDUCTOR = "conductor"
    DIELECTRIC = "dielectric"


class Material(StrictModel):
    id: str = Field(pattern=ID_PATTERN)
    name: str = Field(min_length=1, max_length=80)
    kind: MaterialKind
    relative_permittivity: float | None = Field(default=None, gt=0)
    loss_tangent: float | None = Field(default=None, ge=0, le=1)
    conductivity_s_per_m: float | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def validate_properties(self):
        if self.kind == MaterialKind.DIELECTRIC and self.relative_permittivity is None:
            raise ValueError("dielectric materials require relative_permittivity")
        if self.kind == MaterialKind.PEC and self.name.casefold() == "copper":
            raise ValueError("PEC must not be falsely described as copper")
        return self


class GeometryBase(StrictModel):
    id: str = Field(pattern=ID_PATTERN)
    name: str = Field(min_length=1, max_length=80)
    component: str = Field(default="component1", pattern=ID_PATTERN)
    material: str | None = Field(default=None, pattern=ID_PATTERN)
    dependencies: list[str] = Field(default_factory=list, max_length=64)
    operation_order: int = Field(default=0, ge=0, le=10000)


class Brick(GeometryBase):
    type: Literal["brick"] = "brick"
    x: tuple[Expression, Expression]
    y: tuple[Expression, Expression]
    z: tuple[Expression, Expression]


class Cylinder(GeometryBase):
    type: Literal["cylinder"] = "cylinder"
    axis: Literal["x", "y", "z"] = "z"
    outer_radius: Expression
    inner_radius: Expression = 0
    axis_range: tuple[Expression, Expression]
    center: tuple[Expression, Expression] = (0, 0)


class Sphere(GeometryBase):
    type: Literal["sphere"] = "sphere"
    center: Point3D
    radius: Expression


class Cone(GeometryBase):
    type: Literal["cone"] = "cone"
    axis: Literal["x", "y", "z"] = "z"
    axis_range: tuple[Expression, Expression]
    center: tuple[Expression, Expression] = (0, 0)
    radius1: Expression
    radius2: Expression


class SheetRectangle(GeometryBase):
    type: Literal["sheet_rectangle"] = "sheet_rectangle"
    plane: Literal["xy", "xz", "yz"] = "xy"
    range1: tuple[Expression, Expression]
    range2: tuple[Expression, Expression]
    position: Expression = 0


class Polygon(GeometryBase):
    type: Literal["polygon"] = "polygon"
    plane: Literal["xy", "xz", "yz"] = "xy"
    points: list[tuple[Expression, Expression]] = Field(min_length=3, max_length=256)
    position: Expression = 0


class PolygonExtrusion(GeometryBase):
    type: Literal["polygon_extrusion"] = "polygon_extrusion"
    plane: Literal["xy", "xz", "yz"] = "xy"
    points: list[tuple[Expression, Expression]] = Field(min_length=3, max_length=256)
    range: tuple[Expression, Expression]


class Polyline(GeometryBase):
    type: Literal["polyline"] = "polyline"
    points: list[Point3D] = Field(min_length=2, max_length=512)
    radius: Expression | None = None


class Curve(GeometryBase):
    type: Literal["curve"] = "curve"
    curve_kind: Literal["line", "arc", "spline"]
    points: list[Point3D] = Field(min_length=2, max_length=512)


class ImportedGeometryReference(GeometryBase):
    type: Literal["imported_geometry"] = "imported_geometry"
    reference: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


GeometryPrimitive = Annotated[
    Brick
    | Cylinder
    | Sphere
    | Cone
    | SheetRectangle
    | Polygon
    | PolygonExtrusion
    | Polyline
    | Curve
    | ImportedGeometryReference,
    Field(discriminator="type"),
]


class OperationType(StrEnum):
    UNION = "union"
    SUBTRACT = "subtract"
    INTERSECT = "intersect"
    TRANSLATE = "translate"
    ROTATE = "rotate"
    MIRROR = "mirror"
    SCALE = "scale"
    DUPLICATE = "duplicate"
    LINEAR_ARRAY = "linear_array"
    CIRCULAR_ARRAY = "circular_array"
    RENAME = "rename"
    DELETE = "delete"


class GeometryOperation(StrictModel):
    id: str = Field(pattern=ID_PATTERN)
    type: OperationType
    targets: list[str] = Field(min_length=1, max_length=64)
    output: str | None = Field(default=None, pattern=ID_PATTERN)
    vector: Point3D | None = None
    angles: Point3D | None = None
    center: Point3D = (0, 0, 0)
    factor: Expression | None = None
    count: int | None = Field(default=None, ge=2, le=256)
    axis: Literal["x", "y", "z"] | None = None
    new_name: str | None = Field(default=None, max_length=80)
    dependencies: list[str] = Field(default_factory=list, max_length=64)
    operation_order: int = Field(ge=0, le=10000)


class Excitation(StrictModel):
    id: str = Field(pattern=ID_PATTERN)
    type: Literal["discrete_port", "waveguide_port"]
    name: str = Field(min_length=1, max_length=80)
    p1: Point3D
    p2: Point3D
    impedance_ohm: float = Field(default=50, gt=0, le=1000)
    positive_conductor: str | None = Field(default=None, pattern=ID_PATTERN)
    negative_conductor: str | None = Field(default=None, pattern=ID_PATTERN)
    dependencies: list[str] = Field(default_factory=list)


class Boundary(StrictModel):
    xmin: Literal["open", "expanded_open", "electric", "magnetic", "periodic"]
    xmax: Literal["open", "expanded_open", "electric", "magnetic", "periodic"]
    ymin: Literal["open", "expanded_open", "electric", "magnetic", "periodic"]
    ymax: Literal["open", "expanded_open", "electric", "magnetic", "periodic"]
    zmin: Literal["open", "expanded_open", "electric", "magnetic", "periodic"]
    zmax: Literal["open", "expanded_open", "electric", "magnetic", "periodic"]
    airbox_distance: Expression | None = None


class SolverConfiguration(StrictModel):
    type: Literal["time_domain", "frequency_domain"]
    frequency_min: Expression
    frequency_max: Expression


class MeshConfiguration(StrictModel):
    lines_per_wavelength: float = Field(default=20, ge=4, le=100)
    estimated_cells: int | None = Field(default=None, ge=1)
    local_refinements: list[dict[str, Any]] = Field(default_factory=list, max_length=64)


class Monitor(StrictModel):
    id: str = Field(pattern=ID_PATTERN)
    type: Literal["farfield", "surface_current", "efield", "hfield"]
    frequency: Expression
    target: str | None = Field(default=None, pattern=ID_PATTERN)


class ParameterSweep(StrictModel):
    id: str = Field(pattern=ID_PATTERN)
    parameter: str = Field(pattern=ID_PATTERN)
    strategy: Literal["linear", "explicit"] = "linear"
    start: float | None = None
    stop: float | None = None
    step: float | None = Field(default=None, gt=0)
    values: list[float] = Field(default_factory=list, max_length=1000)

    def case_count(self) -> int:
        if self.strategy == "explicit":
            return len(self.values)
        if self.start is None or self.stop is None or self.step is None:
            return 0
        if self.stop < self.start:
            return 0
        return int(math.floor((self.stop - self.start) / self.step + 1e-12)) + 1


class OptimizationGoal(StrictModel):
    id: str = Field(pattern=ID_PATTERN)
    metric: Literal["s11_db", "vswr", "gain_dbi", "efficiency"]
    operator: Literal["minimize", "maximize", "lte", "gte"]
    target: float | None = None
    frequency: Expression | None = None
    constraints: list[str] = Field(default_factory=list, max_length=32)


class Traceability(StrictModel):
    source_stage: str = Field(min_length=1, max_length=80)
    source_reference: str = Field(default="", max_length=500)
    model_role: str | None = Field(default=None, max_length=80)


class DesignIR(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    project: ProjectMetadata
    units: Units = Field(default_factory=Units)
    coordinate_system: Literal["cartesian"] = "cartesian"
    parameters: dict[str, Parameter] = Field(default_factory=dict, max_length=256)
    materials: list[Material] = Field(default_factory=list, max_length=64)
    geometry: list[GeometryPrimitive] = Field(default_factory=list, max_length=512)
    operations: list[GeometryOperation] = Field(default_factory=list, max_length=512)
    excitations: list[Excitation] = Field(default_factory=list, max_length=32)
    boundaries: Boundary | None = None
    solver: SolverConfiguration | None = None
    mesh: MeshConfiguration | None = None
    monitors: list[Monitor] = Field(default_factory=list, max_length=128)
    parameter_sweeps: list[ParameterSweep] = Field(default_factory=list, max_length=32)
    optimization_goals: list[OptimizationGoal] = Field(
        default_factory=list, max_length=32
    )
    requested_outputs: list[str] = Field(default_factory=list, max_length=64)
    dependencies: list[str] = Field(default_factory=list, max_length=128)
    source_traceability: list[Traceability] = Field(
        default_factory=list, max_length=128
    )
    warnings: list[str] = Field(default_factory=list, max_length=128)

    @field_validator("parameters")
    @classmethod
    def validate_parameter_names(cls, values):
        pattern = re.compile(ID_PATTERN)
        invalid = [name for name in values if not pattern.fullmatch(name)]
        if invalid:
            raise ValueError(f"invalid parameter names: {', '.join(invalid)}")
        return values

    @model_validator(mode="after")
    def validate_unique_ids(self):
        ids = [
            *(item.id for item in self.materials),
            *(item.id for item in self.geometry),
            *(item.id for item in self.operations),
            *(item.id for item in self.excitations),
            *(item.id for item in self.monitors),
            *(item.id for item in self.parameter_sweeps),
            *(item.id for item in self.optimization_goals),
        ]
        duplicates = sorted({item for item in ids if ids.count(item) > 1})
        if duplicates:
            raise ValueError(
                f"DesignIR IDs must be globally unique: {', '.join(duplicates)}"
            )
        return self


_SAFE_FUNCTIONS = {
    "sqrt": math.sqrt,
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
    "abs": abs,
    "min": min,
    "max": max,
}
_SAFE_CONSTANTS = {"pi": math.pi, "e": math.e}
_BINARY_OPERATORS = {
    ast.Add: lambda a, b: a + b,
    ast.Sub: lambda a, b: a - b,
    ast.Mult: lambda a, b: a * b,
    ast.Div: lambda a, b: a / b,
    ast.Pow: lambda a, b: a**b,
    ast.Mod: lambda a, b: a % b,
}
_UNARY_OPERATORS = {ast.UAdd: lambda a: a, ast.USub: lambda a: -a}


def evaluate_expression(expression: Expression, parameters: dict[str, float]) -> float:
    if isinstance(expression, (int, float)) and not isinstance(expression, bool):
        value = float(expression)
    elif isinstance(expression, str):
        if len(expression) > 256:
            raise ValueError("expression exceeds 256 characters")
        try:
            tree = ast.parse(expression, mode="eval")
        except SyntaxError as exc:
            raise ValueError(f"invalid expression: {expression}") from exc
        value = float(_evaluate_node(tree.body, parameters))
    else:
        raise ValueError("expression must be a number or safe arithmetic string")
    if not math.isfinite(value):
        raise ValueError("expression result must be finite")
    return value


def _evaluate_node(node: ast.AST, parameters: dict[str, float]) -> float:
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return float(node.value)
    if isinstance(node, ast.Name):
        if node.id in parameters:
            return parameters[node.id]
        if node.id in _SAFE_CONSTANTS:
            return _SAFE_CONSTANTS[node.id]
        raise ValueError(f"unresolved or forbidden name: {node.id}")
    if isinstance(node, ast.BinOp) and type(node.op) in _BINARY_OPERATORS:
        return _BINARY_OPERATORS[type(node.op)](
            _evaluate_node(node.left, parameters),
            _evaluate_node(node.right, parameters),
        )
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY_OPERATORS:
        return _UNARY_OPERATORS[type(node.op)](_evaluate_node(node.operand, parameters))
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        function = _SAFE_FUNCTIONS.get(node.func.id)
        if function is None or node.keywords:
            raise ValueError(f"forbidden function call: {node.func.id}")
        return float(function(*(_evaluate_node(arg, parameters) for arg in node.args)))
    raise ValueError(f"forbidden expression element: {type(node).__name__}")


def resolve_parameters(design: DesignIR) -> dict[str, float]:
    resolved: dict[str, float] = {}
    pending = dict(design.parameters)
    for _ in range(len(pending) + 1):
        progress = False
        for name, parameter in list(pending.items()):
            try:
                value = evaluate_expression(parameter.value, resolved)
            except ValueError as exc:
                if "unresolved" in str(exc):
                    continue
                raise
            if parameter.minimum is not None and value < parameter.minimum:
                raise ValueError(f"parameter {name} is below its minimum")
            if parameter.maximum is not None and value > parameter.maximum:
                raise ValueError(f"parameter {name} is above its maximum")
            resolved[name] = value
            del pending[name]
            progress = True
        if not pending:
            return resolved
        if not progress:
            break
    raise ValueError(f"unresolved or cyclic parameters: {', '.join(sorted(pending))}")
