import unittest

from prompt2cst.cst_bridge import sanitize_project_name
from prompt2cst.cst_macros import (
    complete_patch_preview,
    complete_parametric_preview,
    complete_wire_monopole_preview,
    dipole_parametric_spec,
    patch_geometry_history,
    test_brick_history,
    wire_monopole_geometry_history,
    wire_monopole_port_history,
)
from prompt2cst.design import (
    DipoleInputs,
    MonopoleInputs,
    PatchInputs,
    calculate_center_fed_dipole,
    calculate_rectangular_patch,
    calculate_wire_monopole,
)


class MacroGenerationTests(unittest.TestCase):
    def setUp(self):
        self.design = calculate_rectangular_patch(PatchInputs())
        self.monopole = calculate_wire_monopole(MonopoleInputs())
        self.dipole = calculate_center_fed_dipole(DipoleInputs())

    def test_brick_macro_matches_verified_object(self):
        macro = test_brick_history()
        self.assertIn('.Name "MCP_Probe_Brick"', macro)
        self.assertIn('.Material "PEC"', macro)
        self.assertIn('.Xrange "-5", "5"', macro)

    def test_patch_geometry_contains_expected_solids(self):
        macro = patch_geometry_history(self.design)
        for name in (
            "Substrate",
            "Ground",
            "Patch_Main",
            "Patch_Lower_Left",
            "Patch_Lower_Right",
            "Feed_Line",
        ):
            self.assertIn(f'.Name "{name}"', macro)

    def test_preview_has_no_general_code_execution(self):
        preview = complete_patch_preview(self.design)
        combined = "\n".join(preview.values()).lower()
        self.assertNotIn("shell", combined)
        self.assertNotIn("powershell", combined)
        self.assertNotIn("createobject", combined)

    def test_project_name_is_sanitized(self):
        self.assertEqual(
            sanitize_project_name(r"..\bad name.cst"),
            "bad_name",
        )

    def test_monopole_geometry_contains_ground_and_cylinder(self):
        macro = wire_monopole_geometry_history(self.monopole)
        self.assertIn('With Cylinder', macro)
        self.assertIn('.Name "Monopole"', macro)
        self.assertIn('.OuterRadius "0.612"', macro)
        self.assertIn('.Zrange "1.5", "32.1"', macro)
        self.assertIn('.Name "Ground"', macro)

    def test_monopole_port_spans_feed_gap(self):
        macro = wire_monopole_port_history(self.monopole)
        self.assertIn('With DiscretePort', macro)
        self.assertIn('.Impedance "50"', macro)
        self.assertIn('.SetP1 "False", "0", "0", "0"', macro)
        self.assertIn('.SetP2 "False", "0", "0", "1.5"', macro)

    def test_monopole_preview_contains_no_solver_start(self):
        preview = complete_wire_monopole_preview(self.monopole)
        combined = "\n".join(preview.values())
        self.assertNotIn("Solver.Start", combined)

    def test_dipole_has_two_arms_and_center_port(self):
        spec = dipole_parametric_spec(self.dipole)
        preview = complete_parametric_preview(spec)
        geometry = preview["geometry"]
        ports = preview["discrete_ports"]

        self.assertIn('.Name "Lower_Arm"', geometry)
        self.assertIn('.Zrange "-31.35", "-0.75"', geometry)
        self.assertIn('.Name "Upper_Arm"', geometry)
        self.assertIn('.Zrange "0.75", "31.35"', geometry)
        self.assertIn('.Label "Dipole_Feed"', ports)
        self.assertIn(
            '.SetP1 "False", "0", "0", "-0.75"',
            ports,
        )
        self.assertIn(
            '.SetP2 "False", "0", "0", "0.75"',
            ports,
        )

    def test_parametric_preview_never_starts_solver(self):
        preview = complete_parametric_preview(
            dipole_parametric_spec(self.dipole)
        )
        self.assertNotIn("Solver.Start", "\n".join(preview.values()))


if __name__ == "__main__":
    unittest.main()
