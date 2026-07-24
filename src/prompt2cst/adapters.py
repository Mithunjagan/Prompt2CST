from __future__ import annotations

from .design import DipoleDesign, MonopoleDesign, PatchDesign
from .design_ir import (
    Boundary,
    Brick,
    Cylinder,
    DesignIR,
    Excitation,
    Material,
    MaterialKind,
    Monitor,
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
        geometry=[
            Cylinder(
                id="lower_arm",
                name="Lower_Arm",
                material="PEC",
                axis="z",
                outer_radius=inputs.wire_radius_mm,
                axis_range=(design.lower_zmin_mm, design.lower_zmax_mm),
                operation_order=1,
            ),
            Cylinder(
                id="upper_arm",
                name="Upper_Arm",
                material="PEC",
                axis="z",
                outer_radius=inputs.wire_radius_mm,
                axis_range=(design.upper_zmin_mm, design.upper_zmax_mm),
                operation_order=2,
            ),
        ],
        excitations=[
            Excitation(
                id="feed",
                type="discrete_port",
                name="Dipole_Feed",
                p1=(0, 0, design.lower_zmax_mm),
                p2=(0, 0, design.upper_zmin_mm),
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


def _expanded_open() -> Boundary:
    return Boundary(
        xmin="expanded_open",
        xmax="expanded_open",
        ymin="expanded_open",
        ymax="expanded_open",
        zmin="expanded_open",
        zmax="expanded_open",
    )
