from __future__ import annotations

import logging
import sys

from mcp.server.fastmcp import FastMCP

from .adapters import (
    dipole_to_design_ir,
    monopole_to_design_ir,
    parametric_to_design_ir,
    patch_to_design_ir,
)
from .catalog import capability_catalog
from .cst_bridge import CSTBridge
from .cst_macros import (
    complete_parametric_preview,
    complete_patch_preview,
    complete_wire_monopole_preview,
    dipole_parametric_spec,
    test_brick_history,
)
from .design import (
    DipoleInputs,
    MonopoleInputs,
    PatchInputs,
    calculate_center_fed_dipole,
    calculate_rectangular_patch,
    calculate_wire_monopole,
)
from .design_ir import Brick, DesignIR, ProjectMetadata
from .parametric import ParametricAntennaSpec
from .plan_service import PlanService

SERVER_INSTRUCTIONS = """
Prompt2CST exposes safe, typed tools for CST Studio Suite 2026. Legacy build
tools create immutable DesignIR previews and never write to CST. Only
execute_approved_plan may reach the CST bridge, and it also requires a
persisted desktop approval record plus the exact plan ID and SHA-256 hash. Do
not claim a solver ran when the tool reports solver_run=false. Use only tools
relevant to the requested antenna.
Never call preview_test_brick as a substitute for a different antenna type.
Call antenna_catalog when the requested family or required CST capability is
unclear. Prefer a dedicated antenna-family tool. Use the custom parametric
tools only for designs that can be represented with validated bricks,
axis-aligned cylinders, materials and discrete ports. Never invent support for
geometry, ports, solvers or result extraction that the catalog marks missing.
""".strip()

mcp = FastMCP("Prompt2CST", instructions=SERVER_INSTRUCTIONS)


def _legacy_build_preview(
    design_ir: DesignIR,
    *,
    confirm: bool,
    overwrite: bool,
) -> dict:
    preview = PlanService().preview_design_plan(design_ir)
    return {
        **preview,
        "status": "approval_required",
        "legacy_requested_confirm": confirm,
        "legacy_requested_overwrite": overwrite,
        "message": (
            "Direct legacy CST writes are disabled. Review this immutable DesignIR "
            "preview, record approval in the desktop, then execute its exact plan ID "
            "and approval hash."
        ),
    }


def _patch_inputs(
    frequency_ghz: float,
    relative_permittivity: float,
    substrate_height_mm: float,
    loss_tangent: float,
    conductor_thickness_mm: float,
    feed_impedance_ohm: float,
    estimated_edge_resistance_ohm: float,
    inset_gap_mm: float,
) -> PatchInputs:
    return PatchInputs(
        frequency_ghz=frequency_ghz,
        relative_permittivity=relative_permittivity,
        substrate_height_mm=substrate_height_mm,
        loss_tangent=loss_tangent,
        conductor_thickness_mm=conductor_thickness_mm,
        feed_impedance_ohm=feed_impedance_ohm,
        estimated_edge_resistance_ohm=estimated_edge_resistance_ohm,
        inset_gap_mm=inset_gap_mm,
    )


@mcp.tool()
def cst_status(test_connection: bool = False) -> dict:
    """Check CST 2026 COM registration; optionally perform a live connection."""

    return CSTBridge().status(test_connection=test_connection)


@mcp.tool()
def antenna_catalog() -> dict:
    """List supported antenna families, safe primitives and limitations."""

    return capability_catalog()


@mcp.tool()
def validate_design_plan(design_ir: DesignIR) -> dict:
    """Run deterministic schema, dependency, geometry and simulation checks."""

    return PlanService().validate_design_plan(design_ir)


@mcp.tool()
def compile_design_plan(design_ir: DesignIR) -> dict:
    """Compile valid DesignIR into deterministic CST History operations."""

    return PlanService().compile_design_plan(design_ir)


@mcp.tool()
def preview_design_plan(design_ir: DesignIR) -> dict:
    """Validate, compile and immutably store one complete read-only plan."""

    return PlanService().preview_design_plan(design_ir)


@mcp.tool()
def get_design_plan(plan_id: str, approval_hash: str = "") -> dict:
    """Return the immutable preview used by the desktop approval sheet."""

    return PlanService().get_design_plan(plan_id, approval_hash)


@mcp.tool()
def execute_approved_plan(
    plan_id: str,
    approval_hash: str,
    approved: bool = False,
    project_name: str = "",
    overwrite: bool = False,
) -> dict:
    """Execute an unchanged plan only after persisted desktop approval."""

    return PlanService().execute_approved_plan(
        plan_id=plan_id,
        approval_hash=approval_hash,
        approved=approved,
        project_name=project_name or None,
        overwrite=overwrite,
    )


@mcp.tool()
def get_execution_status(execution_id: str) -> dict:
    """Return persisted operation-by-operation execution progress."""

    return PlanService().get_execution_status(execution_id)


@mcp.tool()
def cancel_execution(execution_id: str) -> dict:
    """Request safe cancellation between deterministic CST operations."""

    return PlanService().cancel_execution(execution_id)


@mcp.tool()
def extract_simulation_results(execution_id: str) -> dict:
    """Return normalized results or explicitly report unavailable outputs."""

    return PlanService().extract_simulation_results(execution_id)


@mcp.tool()
def preview_test_brick() -> dict:
    """Return the known-good CST history command for the harmless test brick."""

    return {
        "write_performed": False,
        "history_command": test_brick_history(),
        "dimensions_mm": {"x": 10.0, "y": 10.0, "z": 1.0},
        "material": "PEC",
    }


@mcp.tool()
def build_test_brick(
    project_name: str = "mcp_test_brick",
    confirm: bool = False,
    overwrite: bool = False,
) -> dict:
    """Create an immutable test-brick plan; direct writes are disabled."""

    design_ir = DesignIR(
        project=ProjectMetadata(name=project_name, requested_topology="test brick"),
        geometry=[
            Brick(
                id="test_brick",
                name="Prompt2CST_Test_Brick",
                material="PEC",
                x=(-5, 5),
                y=(-5, 5),
                z=(0, 1),
                operation_order=1,
            )
        ],
    )
    return _legacy_build_preview(
        design_ir,
        confirm=confirm,
        overwrite=overwrite,
    )


@mcp.tool()
def preview_rectangular_patch(
    frequency_ghz: float = 2.45,
    relative_permittivity: float = 4.3,
    substrate_height_mm: float = 1.6,
    loss_tangent: float = 0.02,
    conductor_thickness_mm: float = 0.035,
    feed_impedance_ohm: float = 50.0,
    estimated_edge_resistance_ohm: float = 300.0,
    inset_gap_mm: float = 0.5,
    include_history_commands: bool = False,
) -> dict:
    """Calculate and preview a first-pass inset-fed rectangular patch."""

    design = calculate_rectangular_patch(
        _patch_inputs(
            frequency_ghz,
            relative_permittivity,
            substrate_height_mm,
            loss_tangent,
            conductor_thickness_mm,
            feed_impedance_ohm,
            estimated_edge_resistance_ohm,
            inset_gap_mm,
        )
    )
    result = {
        "write_performed": False,
        "design": design.to_dict(),
        "assumptions": [
            "Transmission-line rectangular-patch equations are used.",
            "The ground/substrate margin is three substrate heights per side.",
            "Inset depth uses an estimated edge resistance and needs EM tuning.",
            "PEC approximates the metal in v0.1.",
        ],
    }
    if include_history_commands:
        result["history_commands"] = complete_patch_preview(design)
    return result


@mcp.tool()
def build_rectangular_patch(
    project_name: str,
    frequency_ghz: float = 2.45,
    relative_permittivity: float = 4.3,
    substrate_height_mm: float = 1.6,
    loss_tangent: float = 0.02,
    conductor_thickness_mm: float = 0.035,
    feed_impedance_ohm: float = 50.0,
    estimated_edge_resistance_ohm: float = 300.0,
    inset_gap_mm: float = 0.5,
    include_boundary_setup: bool = True,
    confirm: bool = False,
    overwrite: bool = False,
) -> dict:
    """Create an immutable patch plan; direct legacy writes are disabled."""

    design = calculate_rectangular_patch(
        _patch_inputs(
            frequency_ghz,
            relative_permittivity,
            substrate_height_mm,
            loss_tangent,
            conductor_thickness_mm,
            feed_impedance_ohm,
            estimated_edge_resistance_ohm,
            inset_gap_mm,
        )
    )
    design_ir = patch_to_design_ir(design, project_name)
    if not include_boundary_setup:
        design_ir = design_ir.model_copy(update={"boundaries": None})
    return _legacy_build_preview(
        design_ir,
        confirm=confirm,
        overwrite=overwrite,
    )


def _monopole_inputs(
    frequency_ghz: float,
    wire_length_mm: float,
    wire_radius_mm: float,
    ground_size_mm: float,
    ground_thickness_mm: float,
    feed_gap_mm: float,
    port_impedance_ohm: float,
    sweep_start_ghz: float,
    sweep_stop_ghz: float,
) -> MonopoleInputs:
    return MonopoleInputs(
        frequency_ghz=frequency_ghz,
        wire_length_mm=wire_length_mm,
        wire_radius_mm=wire_radius_mm,
        ground_size_mm=ground_size_mm,
        ground_thickness_mm=ground_thickness_mm,
        feed_gap_mm=feed_gap_mm,
        port_impedance_ohm=port_impedance_ohm,
        sweep_start_ghz=sweep_start_ghz,
        sweep_stop_ghz=sweep_stop_ghz,
    )


@mcp.tool()
def preview_wire_monopole(
    frequency_ghz: float = 2.45,
    wire_length_mm: float = 30.6,
    wire_radius_mm: float = 0.612,
    ground_size_mm: float = 61.2,
    ground_thickness_mm: float = 0.5,
    feed_gap_mm: float = 1.5,
    port_impedance_ohm: float = 50.0,
    sweep_start_ghz: float = 2.0,
    sweep_stop_ghz: float = 3.0,
    include_history_commands: bool = False,
) -> dict:
    """Preview a vertical cylindrical wire monopole, ground and feed port."""

    design = calculate_wire_monopole(
        _monopole_inputs(
            frequency_ghz,
            wire_length_mm,
            wire_radius_mm,
            ground_size_mm,
            ground_thickness_mm,
            feed_gap_mm,
            port_impedance_ohm,
            sweep_start_ghz,
            sweep_stop_ghz,
        )
    )
    warnings = []
    if wire_radius_mm / wire_length_mm >= 0.05:
        warnings.append(
            "The requested radius is large relative to the monopole length; "
            "verify that 6.12 mm was not intended to be 0.612 mm."
        )
    result = {
        "write_performed": False,
        "design": design.to_dict(),
        "port": {
            "type": "discrete",
            "impedance_ohm": port_impedance_ohm,
            "p1_mm": [0.0, 0.0, 0.0],
            "p2_mm": [0.0, 0.0, feed_gap_mm],
        },
        "boundaries": "expanded open in all directions",
        "farfield_monitor_ghz": frequency_ghz,
        "solver_run": False,
        "warnings": warnings,
    }
    if include_history_commands:
        result["history_commands"] = complete_wire_monopole_preview(design)
    return result


@mcp.tool()
def build_wire_monopole(
    project_name: str,
    frequency_ghz: float = 2.45,
    wire_length_mm: float = 30.6,
    wire_radius_mm: float = 0.612,
    ground_size_mm: float = 61.2,
    ground_thickness_mm: float = 0.5,
    feed_gap_mm: float = 1.5,
    port_impedance_ohm: float = 50.0,
    sweep_start_ghz: float = 2.0,
    sweep_stop_ghz: float = 3.0,
    include_port: bool = True,
    include_boundary_setup: bool = True,
    include_farfield_monitor: bool = True,
    confirm: bool = False,
    overwrite: bool = False,
) -> dict:
    """Create an immutable monopole plan; direct legacy writes are disabled."""

    design = calculate_wire_monopole(
        _monopole_inputs(
            frequency_ghz,
            wire_length_mm,
            wire_radius_mm,
            ground_size_mm,
            ground_thickness_mm,
            feed_gap_mm,
            port_impedance_ohm,
            sweep_start_ghz,
            sweep_stop_ghz,
        )
    )
    design_ir = monopole_to_design_ir(design, project_name)
    design_ir = design_ir.model_copy(
        update={
            "excitations": design_ir.excitations if include_port else [],
            "boundaries": design_ir.boundaries if include_boundary_setup else None,
            "monitors": design_ir.monitors if include_farfield_monitor else [],
        }
    )
    return _legacy_build_preview(
        design_ir,
        confirm=confirm,
        overwrite=overwrite,
    )


def _dipole_inputs(
    frequency_ghz: float,
    total_conductor_length_mm: float,
    wire_radius_mm: float,
    feed_gap_mm: float,
    port_impedance_ohm: float,
    sweep_start_ghz: float,
    sweep_stop_ghz: float,
) -> DipoleInputs:
    return DipoleInputs(
        frequency_ghz=frequency_ghz,
        total_conductor_length_mm=total_conductor_length_mm,
        wire_radius_mm=wire_radius_mm,
        feed_gap_mm=feed_gap_mm,
        port_impedance_ohm=port_impedance_ohm,
        sweep_start_ghz=sweep_start_ghz,
        sweep_stop_ghz=sweep_stop_ghz,
    )


@mcp.tool()
def preview_center_fed_dipole(
    frequency_ghz: float = 2.45,
    total_conductor_length_mm: float = 61.2,
    wire_radius_mm: float = 0.5,
    feed_gap_mm: float = 1.5,
    port_impedance_ohm: float = 50.0,
    sweep_start_ghz: float = 2.0,
    sweep_stop_ghz: float = 3.0,
    include_history_commands: bool = False,
) -> dict:
    """Preview a beta center-fed cylindrical dipole and discrete port."""

    design = calculate_center_fed_dipole(
        _dipole_inputs(
            frequency_ghz,
            total_conductor_length_mm,
            wire_radius_mm,
            feed_gap_mm,
            port_impedance_ohm,
            sweep_start_ghz,
            sweep_stop_ghz,
        )
    )
    spec = dipole_parametric_spec(design)
    result = {
        "write_performed": False,
        "family": "center_fed_dipole",
        "design": design.to_dict(),
        "summary": spec.summary(),
        "port": spec.ports[0].model_dump(mode="json"),
        "solver_run": False,
        "warnings": [
            "This family is beta and must be inspected in CST before simulation."
        ],
    }
    if include_history_commands:
        result["history_commands"] = complete_parametric_preview(spec)
    return result


@mcp.tool()
def build_center_fed_dipole(
    project_name: str,
    frequency_ghz: float = 2.45,
    total_conductor_length_mm: float = 61.2,
    wire_radius_mm: float = 0.5,
    feed_gap_mm: float = 1.5,
    port_impedance_ohm: float = 50.0,
    sweep_start_ghz: float = 2.0,
    sweep_stop_ghz: float = 3.0,
    confirm: bool = False,
    overwrite: bool = False,
) -> dict:
    """Create an immutable dipole plan; direct legacy writes are disabled."""

    design = calculate_center_fed_dipole(
        _dipole_inputs(
            frequency_ghz,
            total_conductor_length_mm,
            wire_radius_mm,
            feed_gap_mm,
            port_impedance_ohm,
            sweep_start_ghz,
            sweep_stop_ghz,
        )
    )
    return _legacy_build_preview(
        dipole_to_design_ir(design, project_name),
        confirm=confirm,
        overwrite=overwrite,
    )


@mcp.tool()
def preview_parametric_antenna(
    spec: ParametricAntennaSpec,
    include_history_commands: bool = False,
) -> dict:
    """Preview a safe custom antenna made from validated CST primitives."""

    result = {
        "write_performed": False,
        "family": "custom_parametric",
        "spec": spec.model_dump(mode="json"),
        "summary": spec.summary(),
        "solver_run": False,
        "warnings": [
            "Only the validated primitives in this specification are supported.",
            "Complex topology and electromagnetic correctness require CST inspection.",
        ],
    }
    if include_history_commands:
        result["history_commands"] = complete_parametric_preview(spec)
    return result


@mcp.tool()
def build_parametric_antenna(
    project_name: str,
    spec: ParametricAntennaSpec,
    confirm: bool = False,
    overwrite: bool = False,
) -> dict:
    """Create an immutable custom plan; direct legacy writes are disabled."""

    design_ir = parametric_to_design_ir(spec)
    design_ir = design_ir.model_copy(
        update={"project": design_ir.project.model_copy(update={"name": project_name})}
    )
    return _legacy_build_preview(
        design_ir,
        confirm=confirm,
        overwrite=overwrite,
    )


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        stream=sys.stderr,
        format="%(levelname)s %(name)s: %(message)s",
    )
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
