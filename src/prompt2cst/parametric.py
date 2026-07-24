from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

NAME_PATTERN = r"^[A-Za-z][A-Za-z0-9_-]{0,39}$"
COORDINATE_LIMIT_MM = 5000.0


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DielectricMaterial(StrictModel):
    name: str = Field(pattern=NAME_PATTERN)
    relative_permittivity: float = Field(gt=1.0, le=30.0)
    loss_tangent: float = Field(default=0.0, ge=0.0, le=0.3)


class BrickPrimitive(StrictModel):
    kind: Literal["brick"] = "brick"
    name: str = Field(pattern=NAME_PATTERN)
    material: str = Field(default="PEC", pattern=NAME_PATTERN)
    x_min_mm: float = Field(ge=-COORDINATE_LIMIT_MM, le=COORDINATE_LIMIT_MM)
    x_max_mm: float = Field(ge=-COORDINATE_LIMIT_MM, le=COORDINATE_LIMIT_MM)
    y_min_mm: float = Field(ge=-COORDINATE_LIMIT_MM, le=COORDINATE_LIMIT_MM)
    y_max_mm: float = Field(ge=-COORDINATE_LIMIT_MM, le=COORDINATE_LIMIT_MM)
    z_min_mm: float = Field(ge=-COORDINATE_LIMIT_MM, le=COORDINATE_LIMIT_MM)
    z_max_mm: float = Field(ge=-COORDINATE_LIMIT_MM, le=COORDINATE_LIMIT_MM)

    @model_validator(mode="after")
    def validate_ranges(self):
        if not self.x_min_mm < self.x_max_mm:
            raise ValueError("brick x_min_mm must be less than x_max_mm")
        if not self.y_min_mm < self.y_max_mm:
            raise ValueError("brick y_min_mm must be less than y_max_mm")
        if not self.z_min_mm < self.z_max_mm:
            raise ValueError("brick z_min_mm must be less than z_max_mm")
        return self


class CylinderPrimitive(StrictModel):
    kind: Literal["cylinder"] = "cylinder"
    name: str = Field(pattern=NAME_PATTERN)
    material: str = Field(default="PEC", pattern=NAME_PATTERN)
    axis: Literal["x", "y", "z"] = Field(
        default="z",
        description="Cylinder longitudinal axis.",
    )
    outer_radius_mm: float = Field(gt=0.0, le=1000.0)
    inner_radius_mm: float = Field(default=0.0, ge=0.0, le=999.0)
    axis_min_mm: float = Field(ge=-COORDINATE_LIMIT_MM, le=COORDINATE_LIMIT_MM)
    axis_max_mm: float = Field(ge=-COORDINATE_LIMIT_MM, le=COORDINATE_LIMIT_MM)
    center_u_mm: float = Field(
        default=0.0,
        ge=-COORDINATE_LIMIT_MM,
        le=COORDINATE_LIMIT_MM,
        description=(
            "First transverse center coordinate: y for x-axis cylinders, "
            "x for y/z-axis cylinders."
        ),
    )
    center_v_mm: float = Field(
        default=0.0,
        ge=-COORDINATE_LIMIT_MM,
        le=COORDINATE_LIMIT_MM,
        description=(
            "Second transverse center coordinate: z for x/y-axis cylinders, "
            "y for z-axis cylinders."
        ),
    )

    @model_validator(mode="after")
    def validate_cylinder(self):
        if not self.axis_min_mm < self.axis_max_mm:
            raise ValueError("cylinder axis_min_mm must be less than axis_max_mm")
        if self.inner_radius_mm >= self.outer_radius_mm:
            raise ValueError(
                "cylinder inner_radius_mm must be smaller than outer_radius_mm"
            )
        return self


SolidPrimitive = Annotated[
    BrickPrimitive | CylinderPrimitive,
    Field(discriminator="kind"),
]


class DiscretePortPrimitive(StrictModel):
    number: int = Field(ge=1, le=4)
    label: str = Field(pattern=NAME_PATTERN)
    impedance_ohm: float = Field(default=50.0, ge=10.0, le=200.0)
    p1_x_mm: float = Field(ge=-COORDINATE_LIMIT_MM, le=COORDINATE_LIMIT_MM)
    p1_y_mm: float = Field(ge=-COORDINATE_LIMIT_MM, le=COORDINATE_LIMIT_MM)
    p1_z_mm: float = Field(ge=-COORDINATE_LIMIT_MM, le=COORDINATE_LIMIT_MM)
    p2_x_mm: float = Field(ge=-COORDINATE_LIMIT_MM, le=COORDINATE_LIMIT_MM)
    p2_y_mm: float = Field(ge=-COORDINATE_LIMIT_MM, le=COORDINATE_LIMIT_MM)
    p2_z_mm: float = Field(ge=-COORDINATE_LIMIT_MM, le=COORDINATE_LIMIT_MM)

    @model_validator(mode="after")
    def validate_points(self):
        p1 = (self.p1_x_mm, self.p1_y_mm, self.p1_z_mm)
        p2 = (self.p2_x_mm, self.p2_y_mm, self.p2_z_mm)
        if p1 == p2:
            raise ValueError("discrete port endpoints must differ")
        return self


class ParametricAntennaSpec(StrictModel):
    title: str = Field(
        min_length=1,
        max_length=80,
        description="Human-readable antenna design title.",
    )
    frequency_ghz: float = Field(
        gt=0.01,
        le=100.0,
        description="Target and far-field-monitor frequency in GHz.",
    )
    sweep_start_ghz: float = Field(gt=0.0, le=100.0)
    sweep_stop_ghz: float = Field(gt=0.0, le=100.0)
    materials: list[DielectricMaterial] = Field(
        default_factory=list,
        max_length=8,
        description="Custom normal dielectrics; do not redefine PEC.",
    )
    solids: list[SolidPrimitive] = Field(
        min_length=1,
        max_length=64,
        description="Validated axis-aligned brick and cylinder solids.",
    )
    ports: list[DiscretePortPrimitive] = Field(
        default_factory=list,
        max_length=4,
        description="Discrete S-parameter ports with global-coordinate endpoints.",
    )
    include_open_boundaries: bool = True
    include_farfield_monitor: bool = True

    @model_validator(mode="after")
    def validate_spec(self):
        if not self.sweep_start_ghz < self.sweep_stop_ghz:
            raise ValueError("sweep_start_ghz must be less than sweep_stop_ghz")
        if not (self.sweep_start_ghz <= self.frequency_ghz <= self.sweep_stop_ghz):
            raise ValueError("frequency_ghz must lie inside the sweep")

        material_names = [material.name for material in self.materials]
        if len(material_names) != len(set(material_names)):
            raise ValueError("dielectric material names must be unique")
        if "PEC" in material_names:
            raise ValueError("PEC is built in and must not be redefined")

        solid_names = [solid.name for solid in self.solids]
        if len(solid_names) != len(set(solid_names)):
            raise ValueError("solid names must be unique")

        allowed_materials = {"PEC", *material_names}
        unknown = sorted(
            {
                solid.material
                for solid in self.solids
                if solid.material not in allowed_materials
            }
        )
        if unknown:
            raise ValueError(
                f"solids reference undefined materials: {', '.join(unknown)}"
            )

        port_numbers = [port.number for port in self.ports]
        if len(port_numbers) != len(set(port_numbers)):
            raise ValueError("discrete port numbers must be unique")
        return self

    def summary(self) -> dict:
        return {
            "title": self.title,
            "frequency_ghz": self.frequency_ghz,
            "sweep_ghz": [
                self.sweep_start_ghz,
                self.sweep_stop_ghz,
            ],
            "materials": len(self.materials),
            "solids": len(self.solids),
            "ports": len(self.ports),
            "solid_types": {
                "brick": sum(solid.kind == "brick" for solid in self.solids),
                "cylinder": sum(solid.kind == "cylinder" for solid in self.solids),
            },
            "open_boundaries": self.include_open_boundaries,
            "farfield_monitor": self.include_farfield_monitor,
        }
