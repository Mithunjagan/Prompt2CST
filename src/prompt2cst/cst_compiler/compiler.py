from __future__ import annotations

from dataclasses import asdict, dataclass

from ..design_ir import DesignIR
from ..validation import validate_design
from .booleans import compile_boolean
from .boundaries import compile_boundaries
from .materials import compile_material
from .mesh import compile_mesh
from .monitors import compile_monitor
from .outputs import compile_requested_outputs
from .parameters import compile_parameters
from .ports import compile_port
from .primitives import compile_primitive
from .solvers import compile_solver
from .sweeps import compile_sweep
from .transforms import compile_transform


@dataclass(frozen=True)
class CompiledOperation:
    index: int
    operation_id: str
    category: str
    label: str
    history: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class CompiledDesign:
    schema_version: str
    operations: tuple[CompiledOperation, ...]

    @property
    def normalized_history(self) -> str:
        return "\n\n".join(operation.history for operation in self.operations)

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "operation_count": len(self.operations),
            "operations": [operation.to_dict() for operation in self.operations],
            "normalized_history": self.normalized_history,
        }


def compile_design(design: DesignIR) -> CompiledDesign:
    report = validate_design(design)
    if report.blocking:
        codes = ", ".join(
            item.code for item in report.findings if item.severity == "BLOCKING_ERROR"
        )
        raise ValueError(f"DesignIR has blocking validation errors: {codes}")
    parameters = report.resolved_parameters
    pending: list[tuple[str, str, str, str]] = []

    def add(operation_id: str, category: str, label: str, history: str) -> None:
        if history.strip():
            pending.append((operation_id, category, label, history.strip()))

    add(
        "units",
        "configuration",
        "Prompt2CST: Set units",
        """
With Units
    .Geometry "mm"
    .Frequency "GHz"
    .Time "ns"
End With
""",
    )
    add(
        "parameters",
        "parameters",
        "Prompt2CST: Define parameters",
        compile_parameters(parameters),
    )
    for material in sorted(design.materials, key=lambda item: item.id):
        add(
            material.id,
            "material",
            f"Prompt2CST: Material {material.name}",
            compile_material(material),
        )
    names = {item.id: f"{item.component}:{item.name}" for item in design.geometry}
    for item in sorted(
        design.geometry, key=lambda value: (value.operation_order, value.id)
    ):
        add(
            item.id,
            "primitive",
            f"Prompt2CST: Create {item.name}",
            compile_primitive(item, parameters),
        )
    for operation in sorted(
        design.operations, key=lambda value: (value.operation_order, value.id)
    ):
        if str(operation.type) in {"union", "subtract", "intersect"}:
            history = compile_boolean(operation, names)
        else:
            history = compile_transform(operation, names, parameters)
        add(
            operation.id,
            "geometry_operation",
            f"Prompt2CST: {operation.type} {operation.id}",
            history,
        )
        if operation.output:
            names[operation.output] = names[operation.targets[0]]
    for number, port in enumerate(
        sorted(design.excitations, key=lambda item: item.id), 1
    ):
        add(
            port.id,
            "port",
            f"Prompt2CST: Port {port.name}",
            compile_port(port, parameters, number),
        )
    if design.solver:
        add(
            "solver",
            "simulation",
            "Prompt2CST: Solver configuration",
            compile_solver(design.solver, parameters),
        )
    if design.boundaries:
        add(
            "boundaries",
            "simulation",
            "Prompt2CST: Boundaries",
            compile_boundaries(design.boundaries),
        )
    if design.mesh:
        add("mesh", "mesh", "Prompt2CST: Mesh", compile_mesh(design.mesh))
    for monitor in sorted(design.monitors, key=lambda item: item.id):
        add(
            monitor.id,
            "monitor",
            f"Prompt2CST: Monitor {monitor.id}",
            compile_monitor(monitor, parameters),
        )
    for sweep in sorted(design.parameter_sweeps, key=lambda item: item.id):
        add(sweep.id, "sweep", f"Prompt2CST: Sweep {sweep.id}", compile_sweep(sweep))
    add(
        "outputs",
        "outputs",
        "Prompt2CST: Requested outputs",
        compile_requested_outputs(design.requested_outputs),
    )

    operations = tuple(
        CompiledOperation(index, operation_id, category, label, history)
        for index, (operation_id, category, label, history) in enumerate(pending, 1)
    )
    return CompiledDesign("1.0", operations)
