import unittest

from pydantic import ValidationError

from prompt2cst.adapters import (
    dipole_to_design_ir,
    monopole_to_design_ir,
    patch_to_design_ir,
)
from prompt2cst.cst_compiler import compile_design
from prompt2cst.design import (
    DipoleInputs,
    MonopoleInputs,
    PatchInputs,
    calculate_center_fed_dipole,
    calculate_rectangular_patch,
    calculate_wire_monopole,
)
from prompt2cst.design_ir import (
    Boundary,
    Brick,
    DesignIR,
    Excitation,
    GeometryOperation,
    ImportedGeometryReference,
    Material,
    MaterialKind,
    Monitor,
    OperationType,
    ProjectMetadata,
    SolverConfiguration,
    evaluate_expression,
)
from prompt2cst.validation import Severity, validate_design


def boundaries():
    return Boundary(
        xmin="expanded_open",
        xmax="expanded_open",
        ymin="expanded_open",
        ymax="expanded_open",
        zmin="expanded_open",
        zmax="expanded_open",
    )


def printed_monopole() -> DesignIR:
    return DesignIR(
        project=ProjectMetadata(
            name="Printed monopole", requested_topology="printed monopole"
        ),
        materials=[
            Material(
                id="fr4",
                name="FR-4",
                kind=MaterialKind.DIELECTRIC,
                relative_permittivity=4.3,
                loss_tangent=0.02,
            )
        ],
        geometry=[
            Brick(
                id="substrate",
                name="Substrate",
                material="fr4",
                x=(-20, 20),
                y=(0, 50),
                z=(0, 1.6),
                operation_order=1,
            ),
            Brick(
                id="ground",
                name="Partial_Ground",
                material="PEC",
                x=(-20, 20),
                y=(0, 18),
                z=(1.6, 1.635),
                operation_order=2,
            ),
            Brick(
                id="feed",
                name="Feed",
                material="PEC",
                x=(-1.5, 1.5),
                y=(18, 30),
                z=(1.6, 1.635),
                operation_order=3,
            ),
            Brick(
                id="radiator",
                name="Radiator",
                material="PEC",
                x=(-8, 8),
                y=(30, 47),
                z=(1.6, 1.635),
                operation_order=4,
            ),
        ],
        operations=[
            GeometryOperation(
                id="join_top",
                type=OperationType.UNION,
                targets=["feed", "radiator"],
                output="printed_conductor",
                operation_order=5,
            )
        ],
        excitations=[
            Excitation(
                id="port",
                type="discrete_port",
                name="Feed_Port",
                p1=(0, 18, 1.635),
                p2=(0, 18, 1.635),
                impedance_ohm=50,
            )
        ],
        boundaries=boundaries(),
        solver=SolverConfiguration(
            type="frequency_domain", frequency_min=2, frequency_max=3
        ),
    )


class DesignIRTests(unittest.TestCase):
    def test_safe_expression_parser(self):
        self.assertEqual(evaluate_expression("2 * W + sqrt(4)", {"W": 3}), 8)
        for expression in (
            "__import__('os').system('whoami')",
            "open('secret')",
            "x.__class__",
            "[x for x in [1]]",
        ):
            with self.assertRaises(ValueError, msg=expression):
                evaluate_expression(expression, {"x": 1})

    def test_import_reference_rejects_paths(self):
        with self.assertRaises(ValidationError):
            ImportedGeometryReference(
                id="bad",
                name="Bad",
                material="PEC",
                reference=r"..\secret.step",
            )

    def test_existing_families_compile_through_design_ir(self):
        designs = [
            monopole_to_design_ir(calculate_wire_monopole(MonopoleInputs())),
            dipole_to_design_ir(calculate_center_fed_dipole(DipoleInputs())),
            patch_to_design_ir(calculate_rectangular_patch(PatchInputs())),
        ]
        for design in designs:
            with self.subTest(topology=design.project.requested_topology):
                report = validate_design(design)
                self.assertFalse(report.blocking, report.to_dict())
                compiled = compile_design(design)
                self.assertGreater(len(compiled.operations), 3)
                self.assertNotIn("Solver.Start", compiled.normalized_history)

    def test_printed_monopole_union_compiles(self):
        design = printed_monopole()
        design.excitations = []
        compiled = compile_design(design)
        self.assertIn(
            'Solid.Add "component1:Feed", "component1:Radiator"',
            compiled.normalized_history,
        )

    def test_slotted_patch_subtraction_compiles(self):
        design = DesignIR(
            project=ProjectMetadata(name="Slotted patch"),
            geometry=[
                Brick(
                    id="patch",
                    name="Patch",
                    material="PEC",
                    x=(-10, 10),
                    y=(-8, 8),
                    z=(1.6, 1.635),
                    operation_order=1,
                ),
                Brick(
                    id="slot",
                    name="Slot_Tool",
                    material="PEC",
                    x=(-1, 1),
                    y=(-4, 4),
                    z=(1.5, 1.7),
                    operation_order=2,
                ),
            ],
            operations=[
                GeometryOperation(
                    id="cut_slot",
                    type="subtract",
                    targets=["patch", "slot"],
                    operation_order=3,
                )
            ],
        )
        compiled = compile_design(design)
        self.assertIn(
            'Solid.Subtract "component1:Patch", "component1:Slot_Tool"',
            compiled.normalized_history,
        )

    def test_rotation_and_linear_array_compile(self):
        design = DesignIR(
            project=ProjectMetadata(name="Array"),
            geometry=[
                Brick(
                    id="element",
                    name="Element",
                    material="PEC",
                    x=(0, 2),
                    y=(0, 10),
                    z=(0, 0.1),
                    operation_order=1,
                )
            ],
            operations=[
                GeometryOperation(
                    id="rotate",
                    type="rotate",
                    targets=["element"],
                    angles=(0, 0, 45),
                    operation_order=2,
                ),
                GeometryOperation(
                    id="array",
                    type="linear_array",
                    targets=["element"],
                    vector=(12, 0, 0),
                    count=4,
                    operation_order=3,
                ),
            ],
        )
        history = compile_design(design).normalized_history
        self.assertIn('.Transform "Shape", "Rotate"', history)
        self.assertIn('.Repetitions "4"', history)

    def test_invalid_union_warns(self):
        design = DesignIR(
            project=ProjectMetadata(name="Invalid union"),
            geometry=[
                Brick(
                    id="a",
                    name="A",
                    material="PEC",
                    x=(0, 1),
                    y=(0, 1),
                    z=(0, 1),
                    operation_order=1,
                ),
                Brick(
                    id="b",
                    name="B",
                    material="PEC",
                    x=(10, 11),
                    y=(0, 1),
                    z=(0, 1),
                    operation_order=2,
                ),
            ],
            operations=[
                GeometryOperation(
                    id="union", type="union", targets=["a", "b"], operation_order=3
                )
            ],
        )
        report = validate_design(design)
        finding = next(
            item for item in report.findings if item.code == "union.non_touching"
        )
        self.assertEqual(finding.severity, Severity.WARNING)

    def test_invalid_subtraction_blocks(self):
        design = DesignIR(
            project=ProjectMetadata(name="Invalid subtraction"),
            geometry=[
                Brick(
                    id="a",
                    name="A",
                    material="PEC",
                    x=(0, 1),
                    y=(0, 1),
                    z=(0, 1),
                    operation_order=1,
                ),
                Brick(
                    id="b",
                    name="B",
                    material="PEC",
                    x=(10, 11),
                    y=(0, 1),
                    z=(0, 1),
                    operation_order=2,
                ),
            ],
            operations=[
                GeometryOperation(
                    id="cut", type="subtract", targets=["a", "b"], operation_order=3
                )
            ],
        )
        self.assertTrue(validate_design(design).blocking)

    def test_invalid_port_monitor_and_material_block(self):
        design = DesignIR(
            project=ProjectMetadata(name="Invalid simulation"),
            geometry=[
                Brick(
                    id="metal",
                    name="Metal",
                    material="missing",
                    x=(0, 1),
                    y=(0, 1),
                    z=(0, 1),
                    operation_order=1,
                )
            ],
            excitations=[
                Excitation(
                    id="port",
                    type="discrete_port",
                    name="Port",
                    p1=(5, 5, 5),
                    p2=(6, 6, 6),
                )
            ],
            boundaries=boundaries(),
            solver=SolverConfiguration(
                type="frequency_domain", frequency_min=2, frequency_max=3
            ),
            monitors=[Monitor(id="monitor", type="farfield", frequency=5)],
        )
        codes = {item.code for item in validate_design(design).findings}
        self.assertIn("material.undefined", codes)
        self.assertIn("port.endpoint_not_touching", codes)
        self.assertIn("monitor.outside_range", codes)

    def test_unsupported_capability_is_honest(self):
        design = DesignIR(
            project=ProjectMetadata(name="Import"),
            geometry=[
                ImportedGeometryReference(
                    id="imported",
                    name="Imported",
                    material="PEC",
                    reference="approved.step",
                )
            ],
        )
        findings = validate_design(design).findings
        self.assertTrue(
            any(
                item.code == "capability.unsupported"
                and "geometry.imported_geometry" in item.message
                for item in findings
            )
        )

    def test_compiler_is_deterministic(self):
        design = monopole_to_design_ir(calculate_wire_monopole(MonopoleInputs()))
        self.assertEqual(
            compile_design(design).normalized_history,
            compile_design(design).normalized_history,
        )


if __name__ == "__main__":
    unittest.main()
