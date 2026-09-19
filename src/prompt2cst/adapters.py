from __future__ import annotations

from dataclasses import dataclass

from .design import DipoleDesign, MonopoleDesign, PatchDesign
from .design_ir import (
    Boundary,
    Brick,
    Cylinder,
    DesignIR,
    Excitation,
    Material,
    MaterialKind,
    MeshConfiguration,
    Monitor,
    Parameter,
    ProjectMetadata,
    SolverConfiguration,
    Traceability,
)
from .parametric import BrickPrimitive, CylinderPrimitive, ParametricAntennaSpec


def monopole_to_design_ir(
    design: MonopoleDesign, project_name: str = "wire_monopole"
) -> DesignIR:
    inputs = design.inputs
    return DesignIR(
        project=ProjectMetadata(name=project_name, requested_topology="wire monopole"),
        geometry=[
            Brick(
                id="ground",
                name="Ground",
                material="PEC",
                x=(design.ground_xmin_mm, design.ground_xmax_mm),
                y=(design.ground_ymin_mm, design.ground_ymax_mm),
                z=(design.ground_zmin_mm, design.ground_zmax_mm),
                operation_order=1,
            ),
            Cylinder(
                id="radiator",
                name="Monopole",
                material="PEC",
                axis="z",
                outer_radius=inputs.wire_radius_mm,
                axis_range=(design.monopole_zmin_mm, design.monopole_zmax_mm),
                operation_order=2,
            ),
        ],
        excitations=[
            Excitation(
                id="feed",
                type="discrete_port",
                name="Monopole_Feed",
                p1=(0, 0, 0),
                p2=(0, 0, design.monopole_zmin_mm),
                impedance_ohm=inputs.port_impedance_ohm,
                negative_conductor="ground",
                positive_conductor="radiator",
            )
        ],
        boundaries=_expanded_open(),
        solver=SolverConfiguration(
            type="frequency_domain",
            frequency_min=inputs.sweep_start_ghz,
            frequency_max=inputs.sweep_stop_ghz,
        ),
        monitors=[
            Monitor(id="farfield", type="farfield", frequency=inputs.frequency_ghz)
        ],
        requested_outputs=["s_parameters", "farfield"],
        source_traceability=[
            Traceability(
                source_stage="legacy_adapter", source_reference="wire_monopole"
            )
        ],
    )


def dipole_to_design_ir(
    design: DipoleDesign, project_name: str = "center_fed_dipole"
) -> DesignIR:
    inputs = design.inputs
    return DesignIR(
        project=ProjectMetadata(
            name=project_name, requested_topology="center-fed dipole"
        ),
        # Keep these expressions in CST history.  The two arms and the feed
        # endpoints then genuinely reference CST parameters, so a later
        # StoreParameter(...), Rebuild() changes geometry rather than only
        # changing an external JSON record.
        parameters={
            "dipole_length_mm": Parameter(
                value=inputs.total_conductor_length_mm,
                unit="mm",
                minimum=0.2,
                maximum=2000.0,
                description="Combined length of the two dipole conductors.",
            ),
            "feed_gap_mm": Parameter(
                value=inputs.feed_gap_mm,
                unit="mm",
                minimum=0.01,
                maximum=100.0,
                description="Electrical separation between the two arms.",
            ),
            "wire_radius_mm": Parameter(
                value=inputs.wire_radius_mm,
                unit="mm",
                minimum=0.01,
                maximum=100.0,
                description="Circular conductor radius.",
            ),
        },
        geometry=[
            Cylinder(
                id="lower_arm",
                name="Lower_Arm",
                material="PEC",
                axis="z",
                outer_radius="wire_radius_mm",
                axis_range=(
                    "-feed_gap_mm / 2 - dipole_length_mm / 2",
                    "-feed_gap_mm / 2",
                ),
                operation_order=1,
            ),
            Cylinder(
                id="upper_arm",
                name="Upper_Arm",
                material="PEC",
                axis="z",
                outer_radius="wire_radius_mm",
                axis_range=(
                    "feed_gap_mm / 2",
                    "feed_gap_mm / 2 + dipole_length_mm / 2",
                ),
                operation_order=2,
            ),
        ],
        excitations=[
            Excitation(
                id="feed",
                type="discrete_port",
                name="Dipole_Feed",
                p1=(0, 0, "-feed_gap_mm / 2"),
                p2=(0, 0, "feed_gap_mm / 2"),
                impedance_ohm=inputs.port_impedance_ohm,
                negative_conductor="lower_arm",
                positive_conductor="upper_arm",
            )
        ],
        boundaries=_expanded_open(),
        solver=SolverConfiguration(
            type="frequency_domain",
            frequency_min=inputs.sweep_start_ghz,
            frequency_max=inputs.sweep_stop_ghz,
        ),
        monitors=[
            Monitor(id="farfield", type="farfield", frequency=inputs.frequency_ghz)
        ],
        requested_outputs=["s_parameters", "farfield"],
        source_traceability=[
            Traceability(
                source_stage="legacy_adapter", source_reference="center_fed_dipole"
            )
        ],
    )


def patch_to_design_ir(
    design: PatchDesign, project_name: str = "rectangular_patch"
) -> DesignIR:
    inputs = design.inputs
    half_ground_w = design.ground_width_mm / 2
    half_ground_l = design.ground_length_mm / 2
    half_patch_w = design.patch_width_mm / 2
    half_patch_l = design.patch_length_mm / 2
    half_feed_w = design.feed_width_mm / 2
    half_opening = design.inset_opening_mm / 2
    inset_end_y = -half_patch_l + design.inset_depth_mm
    top = inputs.substrate_height_mm + inputs.conductor_thickness_mm
    bricks = [
        (
            "substrate",
            "Substrate",
            "fr4",
            (-half_ground_w, half_ground_w),
            (-half_ground_l, half_ground_l),
            (0, inputs.substrate_height_mm),
        ),
        (
            "ground",
            "Ground",
            "PEC",
            (-half_ground_w, half_ground_w),
            (-half_ground_l, half_ground_l),
            (-inputs.conductor_thickness_mm, 0),
        ),
        (
            "patch_main",
            "Patch_Main",
            "PEC",
            (-half_patch_w, half_patch_w),
            (inset_end_y, half_patch_l),
            (inputs.substrate_height_mm, top),
        ),
        (
            "patch_left",
            "Patch_Lower_Left",
            "PEC",
            (-half_patch_w, -half_opening),
            (-half_patch_l, inset_end_y),
            (inputs.substrate_height_mm, top),
        ),
        (
            "patch_right",
            "Patch_Lower_Right",
            "PEC",
            (half_opening, half_patch_w),
            (-half_patch_l, inset_end_y),
            (inputs.substrate_height_mm, top),
        ),
        (
            "feed_line",
            "Feed_Line",
            "PEC",
            (-half_feed_w, half_feed_w),
            (-half_ground_l, inset_end_y),
            (inputs.substrate_height_mm, top),
        ),
    ]
    return DesignIR(
        project=ProjectMetadata(
            name=project_name, requested_topology="inset-fed rectangular patch"
        ),
        materials=[
            Material(
                id="fr4",
                name="Prompt2CST_FR4",
                kind=MaterialKind.DIELECTRIC,
                relative_permittivity=inputs.relative_permittivity,
                loss_tangent=inputs.loss_tangent,
            )
        ],
        geometry=[
            Brick(
                id=item[0],
                name=item[1],
                material=item[2],
                x=item[3],
                y=item[4],
                z=item[5],
                operation_order=index,
            )
            for index, item in enumerate(bricks, 1)
        ],
        boundaries=_expanded_open(),
        solver=SolverConfiguration(
            type="frequency_domain",
            frequency_min=design.sweep_start_ghz,
            frequency_max=design.sweep_stop_ghz,
        ),
        requested_outputs=["s_parameters"],
        warnings=[
            "Legacy rectangular patch adapter preserves geometry; excitation remains intentionally absent."
        ],
        source_traceability=[
            Traceability(
                source_stage="legacy_adapter", source_reference="rectangular_patch"
            )
        ],
    )


def parametric_to_design_ir(spec: ParametricAntennaSpec) -> DesignIR:
    materials = [
        Material(
            id=material.name,
            name=material.name,
            kind=MaterialKind.DIELECTRIC,
            relative_permittivity=material.relative_permittivity,
            loss_tangent=material.loss_tangent,
        )
        for material in spec.materials
    ]
    geometry = []
    for index, solid in enumerate(spec.solids, 1):
        if isinstance(solid, BrickPrimitive):
            geometry.append(
                Brick(
                    id=solid.name,
                    name=solid.name,
                    material=solid.material,
                    x=(solid.x_min_mm, solid.x_max_mm),
                    y=(solid.y_min_mm, solid.y_max_mm),
                    z=(solid.z_min_mm, solid.z_max_mm),
                    operation_order=index,
                )
            )
        elif isinstance(solid, CylinderPrimitive):
            geometry.append(
                Cylinder(
                    id=solid.name,
                    name=solid.name,
                    material=solid.material,
                    axis=solid.axis,
                    outer_radius=solid.outer_radius_mm,
                    inner_radius=solid.inner_radius_mm,
                    axis_range=(solid.axis_min_mm, solid.axis_max_mm),
                    center=(solid.center_u_mm, solid.center_v_mm),
                    operation_order=index,
                )
            )
    excitations = [
        Excitation(
            id=f"port_{port.number}",
            type="discrete_port",
            name=port.label,
            p1=(port.p1_x_mm, port.p1_y_mm, port.p1_z_mm),
            p2=(port.p2_x_mm, port.p2_y_mm, port.p2_z_mm),
            impedance_ohm=port.impedance_ohm,
        )
        for port in spec.ports
    ]
    return DesignIR(
        project=ProjectMetadata(
            name=spec.title, requested_topology="custom parametric"
        ),
        materials=materials,
        geometry=geometry,
        excitations=excitations,
        boundaries=_expanded_open() if spec.include_open_boundaries else None,
        solver=SolverConfiguration(
            type="frequency_domain",
            frequency_min=spec.sweep_start_ghz,
            frequency_max=spec.sweep_stop_ghz,
        ),
        monitors=[Monitor(id="farfield", type="farfield", frequency=spec.frequency_ghz)]
        if spec.include_farfield_monitor
        else [],
        source_traceability=[
            Traceability(
                source_stage="legacy_adapter", source_reference="custom_parametric"
            )
        ],
    )


@dataclass(frozen=True)
class TemplePifaInputs:
    """First-pass single-band PIFA for a simplified glasses-temple envelope.

    The frame is a homogeneous support dielectric, the surrounding region is
    CST's default air background, and the ground plane is the local temple
    reference structure.  This is deliberately not a head phantom or a SAR
    model.  Dimensions are starting values, not verified performance claims.
    """

    frequency_ghz: float = 2.45
    sweep_start_ghz: float = 2.0
    sweep_stop_ghz: float = 3.0
    radiator_length_mm: float = 29.0
    radiator_width_mm: float = 8.0
    short_length_mm: float = 2.0
    short_width_mm: float = 1.0
    feed_offset_mm: float = 1.5
    feed_width_mm: float = 1.2
    ground_length_mm: float = 42.0
    ground_width_mm: float = 14.0
    gap_mm: float = 1.0
    stub_length_mm: float = 3.0
    pifa_height_mm: float = 4.0
    frame_thickness_mm: float = 1.5
    copper_thickness_mm: float = 0.035
    frame_relative_permittivity: float = 2.8
    frame_loss_tangent: float = 0.01
    port_impedance_ohm: float = 50.0

    def validate(self) -> None:
        if not 0.1 <= self.frequency_ghz <= 20:
            raise ValueError("frequency_ghz must be between 0.1 and 20")
        if not 0.01 < self.sweep_start_ghz < self.sweep_stop_ghz <= 20:
            raise ValueError("invalid PIFA frequency sweep")
        if not self.sweep_start_ghz <= self.frequency_ghz <= self.sweep_stop_ghz:
            raise ValueError("frequency_ghz must lie inside the sweep")
        positive = {
            "radiator_length_mm": self.radiator_length_mm,
            "radiator_width_mm": self.radiator_width_mm,
            "short_length_mm": self.short_length_mm,
            "short_width_mm": self.short_width_mm,
            "feed_width_mm": self.feed_width_mm,
            "ground_length_mm": self.ground_length_mm,
            "ground_width_mm": self.ground_width_mm,
            "gap_mm": self.gap_mm,
            "stub_length_mm": self.stub_length_mm,
            "pifa_height_mm": self.pifa_height_mm,
            "frame_thickness_mm": self.frame_thickness_mm,
            "copper_thickness_mm": self.copper_thickness_mm,
        }
        if any(value <= 0 for value in positive.values()):
            raise ValueError("all PIFA dimensions must be positive")
        if self.radiator_length_mm + self.stub_length_mm >= self.ground_length_mm:
            raise ValueError("radiator_length_mm + stub_length_mm must fit the ground")
        if self.radiator_width_mm > self.ground_width_mm:
            raise ValueError("radiator_width_mm must fit ground_width_mm")
        if abs(self.feed_offset_mm) + self.feed_width_mm / 2 >= self.radiator_width_mm / 2:
            raise ValueError("feed location must lie within the radiator")
        if self.short_width_mm >= self.radiator_width_mm:
            raise ValueError("short_width_mm must be smaller than radiator_width_mm")


def temple_pifa_to_design_ir(
    inputs: TemplePifaInputs, project_name: str = "temple_pifa"
) -> DesignIR:
    """Create parameter-linked CST geometry for a compact PIFA.

    Each dependent coordinate remains an expression, not a resolved number.
    ``StoreParameter → Rebuild`` therefore modifies the actual CST solids and
    discrete-port placement.
    """
    inputs.validate()
    p = {
        "radiator_length_mm": (inputs.radiator_length_mm, 12.0, 38.0, "Electrical top-plate length."),
        "radiator_width_mm": (inputs.radiator_width_mm, 3.0, 13.0, "Electrical top-plate width."),
        "short_length_mm": (inputs.short_length_mm, 0.5, 8.0, "Ground-contact extent of shorting element."),
        "short_width_mm": (inputs.short_width_mm, 0.3, 4.0, "Width of shorting element."),
        "feed_offset_mm": (inputs.feed_offset_mm, -5.0, 5.0, "X position of the discrete feed."),
        "feed_width_mm": (inputs.feed_width_mm, 0.3, 4.0, "Matching-stub width."),
        "ground_length_mm": (inputs.ground_length_mm, 25.0, 45.0, "Temple reference-plane length."),
        "ground_width_mm": (inputs.ground_width_mm, 8.0, 15.0, "Temple reference-plane width."),
        "gap_mm": (inputs.gap_mm, 0.2, 5.0, "Feed offset from back edge; changes port placement."),
        "stub_length_mm": (inputs.stub_length_mm, 0.0, 10.0, "Open matching-stub extension."),
        "pifa_height_mm": (inputs.pifa_height_mm, 1.0, 8.0, "Top plate height above ground."),
        "frame_thickness_mm": (inputs.frame_thickness_mm, 0.5, 4.0, "Support-frame thickness."),
        "copper_thickness_mm": (inputs.copper_thickness_mm, 0.005, 0.1, "PEC representation thickness."),
    }
    parameters = {
        name: Parameter(value=value, unit="mm", minimum=minimum, maximum=maximum, description=description)
        for name, (value, minimum, maximum, description) in p.items()
    }
    return DesignIR(
        project=ProjectMetadata(name=project_name, requested_topology="temple-mounted PIFA"),
        parameters=parameters,
        materials=[Material(
            id="temple_frame", name="Temple_Frame_Dielectric", kind=MaterialKind.DIELECTRIC,
            relative_permittivity=inputs.frame_relative_permittivity,
            loss_tangent=inputs.frame_loss_tangent,
        )],
        geometry=[
            Brick(id="frame", name="Temple_Frame", material="temple_frame",
                  x=("-ground_width_mm / 2", "ground_width_mm / 2"), y=(0, "ground_length_mm"),
                  z=("-frame_thickness_mm", 0), operation_order=1),
            Brick(id="ground", name="Temple_Ground", material="PEC",
                  x=("-ground_width_mm / 2", "ground_width_mm / 2"), y=(0, "ground_length_mm"),
                  z=(0, "copper_thickness_mm"), operation_order=2),
            Brick(id="radiator", name="PIFA_Radiator", material="PEC",
                  x=("-radiator_width_mm / 2", "radiator_width_mm / 2"),
                  y=("ground_length_mm - radiator_length_mm", "ground_length_mm"),
                  z=("pifa_height_mm", "pifa_height_mm + copper_thickness_mm"), operation_order=3),
            Brick(id="matching_stub", name="PIFA_Matching_Stub", material="PEC",
                  x=("feed_offset_mm - feed_width_mm / 2", "feed_offset_mm + feed_width_mm / 2"),
                  y=("ground_length_mm - radiator_length_mm - stub_length_mm", "ground_length_mm - radiator_length_mm"),
                  z=("pifa_height_mm", "pifa_height_mm + copper_thickness_mm"), operation_order=4),
            Brick(id="shorting_element", name="PIFA_Shorting_Element", material="PEC",
                  x=("-radiator_width_mm / 2", "-radiator_width_mm / 2 + short_width_mm"),
                  y=("ground_length_mm - short_length_mm", "ground_length_mm"),
                  z=("copper_thickness_mm", "pifa_height_mm + copper_thickness_mm"), operation_order=5),
        ],
        excitations=[Excitation(
            id="feed", type="discrete_port", name="PIFA_Feed", impedance_ohm=inputs.port_impedance_ohm,
            p1=("feed_offset_mm", "ground_length_mm - gap_mm", "copper_thickness_mm"),
            p2=("feed_offset_mm", "ground_length_mm - gap_mm", "pifa_height_mm"),
            negative_conductor="ground", positive_conductor="radiator",
        )],
        boundaries=_expanded_open(),
        solver=SolverConfiguration(type="time_domain", frequency_min=inputs.sweep_start_ghz, frequency_max=inputs.sweep_stop_ghz),
        mesh=MeshConfiguration(lines_per_wavelength=25),
        monitors=[Monitor(id="farfield", type="farfield", frequency=inputs.frequency_ghz)],
        requested_outputs=["s_parameters", "farfield"],
        source_traceability=[Traceability(source_stage="pifa_adapter", source_reference="simplified temple PIFA; frame dielectric properties are explicit engineering assumptions")],
        warnings=["CST background is air through expanded-open boundaries.", "No head-loading or SAR model is configured in this free-space first experiment."],
    )


def _expanded_open() -> Boundary:
    return Boundary(
        xmin="expanded_open",
        xmax="expanded_open",
        ymin="expanded_open",
        ymax="expanded_open",
        zmin="expanded_open",
        zmax="expanded_open",
    )
