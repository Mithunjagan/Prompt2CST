from __future__ import annotations

from .design import DipoleDesign, MonopoleDesign, PatchDesign
from .parametric import (
    BrickPrimitive,
    CylinderPrimitive,
    DielectricMaterial,
    DiscretePortPrimitive,
    ParametricAntennaSpec,
)


def format_number(value: float) -> str:
    return f"{value:.9f}".rstrip("0").rstrip(".")


def units_history() -> str:
    return """
With Units
    .Geometry "mm"
    .Frequency "GHz"
    .Time "ns"
End With
""".strip()


def fr4_material_history(design: PatchDesign) -> str:
    inputs = design.inputs
    return f"""
With Material
    .Reset
    .Name "Prompt2CST_FR4"
    .Folder ""
    .FrqType "all"
    .Type "Normal"
    .SetMaterialUnit "GHz", "mm"
    .Epsilon "{format_number(inputs.relative_permittivity)}"
    .Mue "1"
    .TanD "{format_number(inputs.loss_tangent)}"
    .TanDFreq "{format_number(inputs.frequency_ghz)}"
    .TanDGiven "True"
    .Colour "0.15", "0.65", "0.25"
    .Wireframe "False"
    .Transparency "45"
    .Create
End With
""".strip()


def test_brick_history() -> str:
    return """
With Brick
    .Reset
    .Name "MCP_Probe_Brick"
    .Component "component1"
    .Material "PEC"
    .Xrange "-5", "5"
    .Yrange "-5", "5"
    .Zrange "0", "1"
    .Create
End With
""".strip()


def patch_geometry_history(design: PatchDesign) -> str:
    i = design.inputs
    half_ground_w = design.ground_width_mm / 2.0
    half_ground_l = design.ground_length_mm / 2.0
    half_patch_w = design.patch_width_mm / 2.0
    half_patch_l = design.patch_length_mm / 2.0
    half_feed_w = design.feed_width_mm / 2.0
    half_opening = design.inset_opening_mm / 2.0
    inset_end_y = -half_patch_l + design.inset_depth_mm
    conductor_top = i.substrate_height_mm + i.conductor_thickness_mm

    brick_data = [
        (
            "Substrate",
            "Prompt2CST_FR4",
            -half_ground_w,
            half_ground_w,
            -half_ground_l,
            half_ground_l,
            0.0,
            i.substrate_height_mm,
        ),
        (
            "Ground",
            "PEC",
            -half_ground_w,
            half_ground_w,
            -half_ground_l,
            half_ground_l,
            -i.conductor_thickness_mm,
            0.0,
        ),
        (
            "Patch_Main",
            "PEC",
            -half_patch_w,
            half_patch_w,
            inset_end_y,
            half_patch_l,
            i.substrate_height_mm,
            conductor_top,
        ),
        (
            "Patch_Lower_Left",
            "PEC",
            -half_patch_w,
            -half_opening,
            -half_patch_l,
            inset_end_y,
            i.substrate_height_mm,
            conductor_top,
        ),
        (
            "Patch_Lower_Right",
            "PEC",
            half_opening,
            half_patch_w,
            -half_patch_l,
            inset_end_y,
            i.substrate_height_mm,
            conductor_top,
        ),
        (
            "Feed_Line",
            "PEC",
            -half_feed_w,
            half_feed_w,
            -half_ground_l,
            inset_end_y,
            i.substrate_height_mm,
            conductor_top,
        ),
    ]

    blocks = []
    for name, material, xmin, xmax, ymin, ymax, zmin, zmax in brick_data:
        blocks.append(
            f"""
With Brick
    .Reset
    .Name "{name}"
    .Component "component1"
    .Material "{material}"
    .Xrange "{format_number(xmin)}", "{format_number(xmax)}"
    .Yrange "{format_number(ymin)}", "{format_number(ymax)}"
    .Zrange "{format_number(zmin)}", "{format_number(zmax)}"
    .Create
End With
""".strip()
        )

    return "\n\n".join(blocks)


def frequency_and_boundary_values(
    sweep_start_ghz: float,
    sweep_stop_ghz: float,
) -> str:
    return f"""
Solver.FrequencyRange "{format_number(sweep_start_ghz)}", "{format_number(sweep_stop_ghz)}"

With Boundary
    .Xmin "expanded open"
    .Xmax "expanded open"
    .Ymin "expanded open"
    .Ymax "expanded open"
    .Zmin "expanded open"
    .Zmax "expanded open"
    .ApplyInAllDirections "False"
End With
""".strip()


def frequency_and_boundary_history(
    design: PatchDesign | MonopoleDesign | DipoleDesign,
) -> str:
    return frequency_and_boundary_values(
        design.sweep_start_ghz,
        design.sweep_stop_ghz,
    )


def complete_patch_preview(design: PatchDesign) -> dict[str, str]:
    return {
        "units": units_history(),
        "material": fr4_material_history(design),
        "geometry": patch_geometry_history(design),
        "frequency_and_boundaries": frequency_and_boundary_history(design),
    }


def wire_monopole_geometry_history(design: MonopoleDesign) -> str:
    i = design.inputs
    return f"""
With Brick
    .Reset
    .Name "Ground"
    .Component "component1"
    .Material "PEC"
    .Xrange "{format_number(design.ground_xmin_mm)}", "{format_number(design.ground_xmax_mm)}"
    .Yrange "{format_number(design.ground_ymin_mm)}", "{format_number(design.ground_ymax_mm)}"
    .Zrange "{format_number(design.ground_zmin_mm)}", "{format_number(design.ground_zmax_mm)}"
    .Create
End With

With Cylinder
    .Reset
    .Name "Monopole"
    .Component "component1"
    .Material "PEC"
    .OuterRadius "{format_number(i.wire_radius_mm)}"
    .InnerRadius "0"
    .Axis "z"
    .Zrange "{format_number(design.monopole_zmin_mm)}", "{format_number(design.monopole_zmax_mm)}"
    .Xcenter "0"
    .Ycenter "0"
    .Segments "0"
    .Create
End With
""".strip()


def wire_monopole_port_history(design: MonopoleDesign) -> str:
    i = design.inputs
    return f"""
With DiscretePort
    .Reset
    .PortNumber "1"
    .Type "SParameter"
    .Label "Monopole_Feed"
    .Impedance "{format_number(i.port_impedance_ohm)}"
    .Voltage "1.0"
    .Current "1.0"
    .SetP1 "False", "0", "0", "0"
    .SetP2 "False", "0", "0", "{format_number(i.feed_gap_mm)}"
    .InvertDirection "False"
    .LocalCoordinates "False"
    .Monitor "True"
    .Create
End With
""".strip()


def farfield_monitor_values(frequency_ghz: float) -> str:
    return f"""
With Monitor
    .Reset
    .Name "Farfield_{format_number(frequency_ghz)}GHz"
    .Dimension "Volume"
    .Domain "Frequency"
    .FieldType "Farfield"
    .Frequency "{format_number(frequency_ghz)}"
    .UseSubvolume "False"
    .Create
End With
""".strip()


def farfield_monitor_history(
    design: MonopoleDesign | DipoleDesign,
) -> str:
    return farfield_monitor_values(design.inputs.frequency_ghz)


def complete_wire_monopole_preview(
    design: MonopoleDesign,
) -> dict[str, str]:
    return {
        "units": units_history(),
        "geometry": wire_monopole_geometry_history(design),
        "discrete_port": wire_monopole_port_history(design),
        "frequency_and_boundaries": frequency_and_boundary_history(design),
        "farfield_monitor": farfield_monitor_history(design),
    }


def dielectric_material_history(
    material: DielectricMaterial,
    frequency_ghz: float,
) -> str:
    return f"""
With Material
    .Reset
    .Name "{material.name}"
    .Folder ""
    .FrqType "all"
    .Type "Normal"
    .SetMaterialUnit "GHz", "mm"
    .Epsilon "{format_number(material.relative_permittivity)}"
    .Mue "1"
    .TanD "{format_number(material.loss_tangent)}"
    .TanDFreq "{format_number(frequency_ghz)}"
    .TanDGiven "True"
    .Colour "0.18", "0.55", "0.78"
    .Wireframe "False"
    .Transparency "45"
    .Create
End With
""".strip()


def parametric_materials_history(spec: ParametricAntennaSpec) -> str:
    return "\n\n".join(
        dielectric_material_history(material, spec.frequency_ghz)
        for material in spec.materials
    )


def _brick_primitive_history(solid: BrickPrimitive) -> str:
    return f"""
With Brick
    .Reset
    .Name "{solid.name}"
    .Component "component1"
    .Material "{solid.material}"
    .Xrange "{format_number(solid.x_min_mm)}", "{format_number(solid.x_max_mm)}"
    .Yrange "{format_number(solid.y_min_mm)}", "{format_number(solid.y_max_mm)}"
    .Zrange "{format_number(solid.z_min_mm)}", "{format_number(solid.z_max_mm)}"
    .Create
End With
""".strip()


def _cylinder_primitive_history(solid: CylinderPrimitive) -> str:
    range_method = {
        "x": "Xrange",
        "y": "Yrange",
        "z": "Zrange",
    }[solid.axis]
    center_methods = {
        "x": ("Ycenter", "Zcenter"),
        "y": ("Xcenter", "Zcenter"),
        "z": ("Xcenter", "Ycenter"),
    }[solid.axis]
    return f"""
With Cylinder
    .Reset
    .Name "{solid.name}"
    .Component "component1"
    .Material "{solid.material}"
    .OuterRadius "{format_number(solid.outer_radius_mm)}"
    .InnerRadius "{format_number(solid.inner_radius_mm)}"
    .Axis "{solid.axis}"
    .{range_method} "{format_number(solid.axis_min_mm)}", "{format_number(solid.axis_max_mm)}"
    .{center_methods[0]} "{format_number(solid.center_u_mm)}"
    .{center_methods[1]} "{format_number(solid.center_v_mm)}"
    .Segments "0"
    .Create
End With
""".strip()


def parametric_geometry_history(spec: ParametricAntennaSpec) -> str:
    blocks = []
    for solid in spec.solids:
        if isinstance(solid, BrickPrimitive):
            blocks.append(_brick_primitive_history(solid))
        else:
            blocks.append(_cylinder_primitive_history(solid))
    return "\n\n".join(blocks)


def _discrete_port_primitive_history(
    port: DiscretePortPrimitive,
) -> str:
    return f"""
With DiscretePort
    .Reset
    .PortNumber "{port.number}"
    .Type "SParameter"
    .Label "{port.label}"
    .Impedance "{format_number(port.impedance_ohm)}"
    .Voltage "1.0"
    .Current "1.0"
    .SetP1 "False", "{format_number(port.p1_x_mm)}", "{format_number(port.p1_y_mm)}", "{format_number(port.p1_z_mm)}"
    .SetP2 "False", "{format_number(port.p2_x_mm)}", "{format_number(port.p2_y_mm)}", "{format_number(port.p2_z_mm)}"
    .InvertDirection "False"
    .LocalCoordinates "False"
    .Monitor "True"
    .Create
End With
""".strip()


def parametric_ports_history(spec: ParametricAntennaSpec) -> str:
    return "\n\n".join(_discrete_port_primitive_history(port) for port in spec.ports)


def complete_parametric_preview(
    spec: ParametricAntennaSpec,
) -> dict[str, str]:
    history = {
        "units": units_history(),
        "materials": parametric_materials_history(spec),
        "geometry": parametric_geometry_history(spec),
        "discrete_ports": parametric_ports_history(spec),
    }
    if spec.include_open_boundaries:
        history["frequency_and_boundaries"] = frequency_and_boundary_values(
            spec.sweep_start_ghz,
            spec.sweep_stop_ghz,
        )
    if spec.include_farfield_monitor:
        history["farfield_monitor"] = farfield_monitor_values(spec.frequency_ghz)
    return {key: value for key, value in history.items() if value}


def dipole_parametric_spec(design: DipoleDesign) -> ParametricAntennaSpec:
    inputs = design.inputs
    return ParametricAntennaSpec(
        title="Center-fed cylindrical dipole",
        frequency_ghz=inputs.frequency_ghz,
        sweep_start_ghz=inputs.sweep_start_ghz,
        sweep_stop_ghz=inputs.sweep_stop_ghz,
        solids=[
            CylinderPrimitive(
                name="Lower_Arm",
                material="PEC",
                axis="z",
                outer_radius_mm=inputs.wire_radius_mm,
                axis_min_mm=design.lower_zmin_mm,
                axis_max_mm=design.lower_zmax_mm,
            ),
            CylinderPrimitive(
                name="Upper_Arm",
                material="PEC",
                axis="z",
                outer_radius_mm=inputs.wire_radius_mm,
                axis_min_mm=design.upper_zmin_mm,
                axis_max_mm=design.upper_zmax_mm,
            ),
        ],
        ports=[
            DiscretePortPrimitive(
                number=1,
                label="Dipole_Feed",
                impedance_ohm=inputs.port_impedance_ohm,
                p1_x_mm=0.0,
                p1_y_mm=0.0,
                p1_z_mm=design.lower_zmax_mm,
                p2_x_mm=0.0,
                p2_y_mm=0.0,
                p2_z_mm=design.upper_zmin_mm,
            )
        ],
        include_open_boundaries=True,
        include_farfield_monitor=True,
    )
