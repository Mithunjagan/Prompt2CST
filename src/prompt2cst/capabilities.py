from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class Capability:
    id: str
    supported: bool
    required_parameters: tuple[str, ...]
    validator: str
    compiler: str | None
    cst_versions: tuple[str, ...] = ("2026",)
    limitations: tuple[str, ...] = ()
    closest_alternative: str | None = None
    extensible: bool = True

    def to_dict(self) -> dict:
        return asdict(self)


_SUPPORTED = {
    "geometry.brick": ("x", "y", "z"),
    "geometry.cylinder": ("axis", "outer_radius", "axis_range", "center"),
    "boolean.union": ("targets",),
    "boolean.subtract": ("targets",),
    "boolean.intersect": ("targets",),
    "transform.translate": ("targets", "vector"),
    "transform.rotate": ("targets", "angles"),
    "transform.mirror": ("targets", "axis"),
    "transform.scale": ("targets", "factor"),
    "transform.duplicate": ("targets", "vector"),
    "transform.linear_array": ("targets", "vector", "count"),
    "transform.rename": ("targets", "new_name"),
    "transform.delete": ("targets",),
    "port.discrete": ("p1", "p2", "impedance_ohm"),
    "boundary.open": ("xmin", "xmax", "ymin", "ymax", "zmin", "zmax"),
    "boundary.expanded_open": ("xmin", "xmax", "ymin", "ymax", "zmin", "zmax"),
    "solver.time_domain": ("frequency_min", "frequency_max"),
    "solver.frequency_domain": ("frequency_min", "frequency_max"),
    "monitor.farfield": ("frequency",),
    "monitor.surface_current": ("frequency",),
    "mesh.global": ("lines_per_wavelength",),
    "sweep.parameter": ("parameter",),
}

_UNSUPPORTED = {
    "geometry.sphere": ("geometry.cylinder",),
    "geometry.cone": ("geometry.cylinder",),
    "geometry.sheet_rectangle": ("geometry.brick",),
    "geometry.polygon": ("geometry.brick",),
    "geometry.polygon_extrusion": ("geometry.brick",),
    "geometry.polyline": ("geometry.cylinder",),
    "geometry.curve": ("geometry.polyline",),
    "geometry.imported_geometry": (),
    "transform.circular_array": ("transform.linear_array",),
    "port.waveguide": ("port.discrete",),
    "mesh.local_refinement": ("mesh.global",),
    "optimization.goal": ("sweep.parameter",),
    "results.live_extraction": (),
}


def capability_registry() -> dict[str, Capability]:
    result = {
        capability_id: Capability(
            id=capability_id,
            supported=True,
            required_parameters=required,
            validator="prompt2cst.validation.validate_design",
            compiler=f"prompt2cst.cst_compiler.{capability_id.replace('.', '_')}",
            limitations=(
                "Generated command syntax requires final inspection on the target CST 2026 installation.",
            ),
        )
        for capability_id, required in _SUPPORTED.items()
    }
    for capability_id, alternatives in _UNSUPPORTED.items():
        result[capability_id] = Capability(
            id=capability_id,
            supported=False,
            required_parameters=(),
            validator="prompt2cst.validation.validate_design",
            compiler=None,
            limitations=("No verified deterministic CST 2026 compiler is installed.",),
            closest_alternative=alternatives[0] if alternatives else None,
        )
    return result


def capability_browser() -> list[dict]:
    return [
        capability.to_dict()
        for capability in sorted(
            capability_registry().values(), key=lambda item: item.id
        )
    ]


def required_capabilities(design) -> set[str]:
    required = {f"geometry.{item.type}" for item in design.geometry}
    operation_mapping = {
        "union": "boolean.union",
        "subtract": "boolean.subtract",
        "intersect": "boolean.intersect",
        "translate": "transform.translate",
        "rotate": "transform.rotate",
        "mirror": "transform.mirror",
        "scale": "transform.scale",
        "duplicate": "transform.duplicate",
        "linear_array": "transform.linear_array",
        "circular_array": "transform.circular_array",
        "rename": "transform.rename",
        "delete": "transform.delete",
    }
    required.update(operation_mapping[str(item.type)] for item in design.operations)
    required.update(
        f"port.{item.type.removesuffix('_port')}" for item in design.excitations
    )
    if design.boundaries:
        modes = set(design.boundaries.model_dump().values())
        required.add(
            "boundary.expanded_open" if "expanded_open" in modes else "boundary.open"
        )
    if design.solver:
        required.add(f"solver.{design.solver.type}")
    required.update(f"monitor.{item.type}" for item in design.monitors)
    if design.mesh:
        required.add("mesh.global")
        if design.mesh.local_refinements:
            required.add("mesh.local_refinement")
    if design.parameter_sweeps:
        required.add("sweep.parameter")
    if design.optimization_goals:
        required.add("optimization.goal")
    return required


def unsupported_for_design(design) -> list[dict]:
    registry = capability_registry()
    missing = []
    for capability_id in sorted(required_capabilities(design)):
        capability = registry.get(capability_id)
        if capability is None or not capability.supported:
            missing.append(
                capability.to_dict()
                if capability
                else {
                    "id": capability_id,
                    "supported": False,
                    "closest_alternative": None,
                    "extensible": True,
                    "limitations": ["Capability is not registered."],
                }
            )
    return missing
