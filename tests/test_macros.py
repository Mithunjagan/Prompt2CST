import unittest
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory

from prompt2cst.cst_bridge import CSTBridge, sanitize_project_name
from prompt2cst.adapters import TemplePifaInputs
from prompt2cst.cst_macros import (
    complete_parametric_preview,
    complete_patch_preview,
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

    def test_run_solver_uses_cst_2026_openfile_active3d_api(self):
        class FakeSolver:
            started = False

            def Start(self):
                self.started = True

        class FakeProject:
            saved = False

            def __init__(self):
                self.solver = FakeSolver()

            def Solver(self):
                return self.solver

            def Save(self):
                self.saved = True

        class FakeApplication:
            opened = None

            def __init__(self):
                self.project = FakeProject()

            def OpenFile(self, path):
                self.opened = path

            def Active3D(self):
                return self.project

        app = FakeApplication()
        bridge = CSTBridge()

        @contextmanager
        def fake_application():
            yield app

        bridge._application = fake_application
        with TemporaryDirectory() as directory:
            project_path = Path(directory) / "audit.cst"
            project_path.write_text("placeholder", encoding="utf-8")
            result = bridge.run_solver(project_path)

        self.assertEqual(result["status"], "completed")
        self.assertEqual(app.opened, str(project_path.resolve()))
        self.assertTrue(app.project.solver.started)
        self.assertTrue(app.project.saved)

    def test_update_parameters_rebuilds_and_saves_real_cst_project(self):
        class FakeProject:
            def __init__(self):
                self.parameters = []
                self.rebuilt = False
                self.saved = False

            def StoreParameter(self, name, value):
                self.parameters.append((name, value))

            def Rebuild(self):
                self.rebuilt = True

            def Save(self):
                self.saved = True

        class FakeApplication:
            def __init__(self):
                self.project = FakeProject()

            def OpenFile(self, _path):
                return None

            def Active3D(self):
                return self.project

        app = FakeApplication()
        bridge = CSTBridge()

        @contextmanager
        def fake_application():
            yield app

        bridge._application = fake_application
        with TemporaryDirectory() as directory:
            project_path = Path(directory) / "parameterized.cst"
            project_path.write_text("placeholder", encoding="utf-8")
            result = bridge.update_parameters(project_path, {"dipole_length_mm": 58.4})

        self.assertEqual(result["status"], "completed")
        self.assertEqual(app.project.parameters, [("dipole_length_mm", 58.4)])
        self.assertTrue(app.project.rebuilt)
        self.assertTrue(app.project.saved)

    def test_read_parameter_reopens_saved_cst_project(self):
        class FakeProject:
            def RestoreDoubleParameter(self, name):
                self.name = name
                return "0.5"
            def GetParameter(self, name):
                self.name = name
                return "0.5"
        class FakeApplication:
            def __init__(self): self.project = FakeProject()
            def OpenFile(self, path): self.path = path
            def Active3D(self): return self.project
        app = FakeApplication()
        bridge = CSTBridge()
        @contextmanager
        def fake_application(): yield app
        bridge._application = fake_application
        with TemporaryDirectory() as directory:
            path = Path(directory) / "parameterized.cst"
            path.write_text("placeholder", encoding="utf-8")
            self.assertEqual(bridge.read_parameter(path, "feed_offset_mm"), 0.5)
        self.assertEqual(app.project.name, "feed_offset_mm")

    def test_temple_pifa_build_uses_compiled_history(self):
        bridge = CSTBridge()
        captured = {}

        def capture(compiled, project_name, overwrite):
            captured["history"] = compiled.normalized_history
            captured["project_name"] = project_name
            return {"status": "completed", "warnings": [], "project_path": "pifa.cst"}

        bridge.execute_compiled_design = capture
        result = bridge.build_temple_pifa(TemplePifaInputs(), "temple_pifa")
        self.assertEqual(result["family"], "temple_pifa")
        self.assertIn('.Name "PIFA_Radiator"', captured["history"])
        self.assertIn('.Name "PIFA_Shorting_Element"', captured["history"])
        self.assertIn('.Label "PIFA_Feed"', captured["history"])

    def test_temple_pifa_impedance_link_records_only_extracted_zin(self):
        bridge = CSTBridge()
        bridge.build_temple_pifa = lambda *_args, **_kwargs: {"project_path": "pifa.cst"}
        bridge.update_parameters = lambda *_args, **_kwargs: {"status": "completed"}
        bridge.run_solver = lambda *_args, **_kwargs: {"status": "completed"}
        values = iter(((62.0, -8.0), (48.0, 1.0)))

        def extract(_path, artifact_tag=""):
            z_re, z_im = next(values)
            return {
                "status": "completed",
                "extracted": {
                    "zin_re": (z_re, "Ohm"), "zin_im": (z_im, "Ohm"),
                    "frequency_samples": ([], "GHz"),
                },
                "raw_extracted": {}, "unavailable": [],
            }

        bridge.extract_results = extract
        with TemporaryDirectory() as directory:
            bridge.output_dir = Path(directory)
            result = bridge.run_temple_pifa_impedance_link_test("pifa", 0.5, 3.0)
        self.assertTrue(result["response_changed"])
        self.assertGreater(result["impedance_change_ohm"], 1.0)
        self.assertEqual(result["geometry_parameter"], "feed_offset_mm")

    def test_monopole_geometry_contains_ground_and_cylinder(self):
        macro = wire_monopole_geometry_history(self.monopole)
        self.assertIn("With Cylinder", macro)
        self.assertIn('.Name "Monopole"', macro)
        self.assertIn('.OuterRadius "0.612"', macro)
        self.assertIn('.Zrange "1.5", "32.1"', macro)
        self.assertIn('.Name "Ground"', macro)

    def test_monopole_port_spans_feed_gap(self):
        macro = wire_monopole_port_history(self.monopole)
        self.assertIn("With DiscretePort", macro)
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
        preview = complete_parametric_preview(dipole_parametric_spec(self.dipole))
        self.assertNotIn("Solver.Start", "\n".join(preview.values()))


if __name__ == "__main__":
    unittest.main()
