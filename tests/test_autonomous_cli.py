from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from prompt2cst.autonomous import extract_requirements, project_status, run_design
from prompt2cst.cli import create_parser
from prompt2cst.local_ai import LocalAIResult
from prompt2cst.openems_backend import build_project, write_project
from prompt2cst.papers import PaperIngestionEngine


class AutonomousWorkflowTests(unittest.TestCase):
    def test_local_ai_flag_is_explicit_opt_in(self):
        parser = create_parser()
        self.assertFalse(parser.parse_args(["design", "Build a PIFA"]).local_ai)
        self.assertTrue(parser.parse_args(["design", "Build a PIFA", "--local-ai"]).local_ai)

    def test_unsupported_family_stops_before_project_creation(self):
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / "project"
            with patch("prompt2cst.autonomous.confirm_prompt_family") as model:
                with self.assertRaisesRegex(ValueError, "research-only"):
                    run_design(
                        "Build a spiral antenna at 868 MHz", project,
                        mode="dry-run", use_local_ai=True,
                    )
            model.assert_not_called()
            self.assertFalse(project.exists())

    def test_local_ai_is_only_an_advisory_to_deterministic_requirements(self):
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / "project"
            with patch(
                "prompt2cst.autonomous.confirm_prompt_family",
                return_value=LocalAIResult("mismatch", "qwen3:0.6b"),
            ) as model:
                result = run_design(
                    "Design a PIFA at 868 MHz", project,
                    mode="dry-run", use_local_ai=True,
                )
            model.assert_called_once_with("Design a PIFA at 868 MHz", "pifa")
            self.assertEqual(result.selected_topology, "pifa")
            requirements = json.loads(
                Path(result.artifacts["requirements"]).read_text(encoding="utf-8")
            )
            self.assertEqual(requirements["center_frequency_hz"], 868_000_000)
            self.assertEqual(requirements["local_ai"]["status"], "mismatch")
            self.assertNotIn("frequency_hz", requirements["local_ai"])

    def test_sub_ghz_prompt_frequency_uses_deterministic_mhz_conversion(self):
        cases = (
            ("Design a LoRa PIFA at 868 MHz", 868_000_000),
            ("Design a Yagi at 915 megahertz", 915_000_000),
            ("Design a helix at 2.45 GHz", 2_450_000_000),
        )
        for prompt, expected_hz in cases:
            with self.subTest(prompt=prompt):
                self.assertAlmostEqual(
                    extract_requirements(prompt)["center_frequency_hz"], expected_hz
                )

    def test_mhz_range_is_converted_before_planning(self):
        requirements = extract_requirements("Design a PIFA for 863 to 870 MHz")
        self.assertAlmostEqual(requirements["frequency_min_ghz"], 0.863)
        self.assertAlmostEqual(requirements["frequency_max_ghz"], 0.870)
        self.assertAlmostEqual(requirements["center_frequency_hz"], 866_500_000)

    def test_lora_band_dry_run_persists_requested_frequency(self):
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / "project"
            result = run_design("Design a LoRa PIFA at 868 MHz", project, mode="dry-run")
            requirements = json.loads(
                (project / "requirements" / "requirements_v2.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(result.status, "planning_validated")
            self.assertEqual(result.selected_topology, "pifa")
            self.assertEqual(requirements["center_frequency_hz"], 868_000_000)

    def test_dry_run_persists_traceable_planning_artifacts(self):
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / "project"
            result = run_design(
                "Design a compact antenna for smart glasses at 2.45 GHz in the temple with S11 < -10 dB",
                project,
                mode="dry-run",
            )
            self.assertEqual(result.status, "planning_validated")
            self.assertEqual(result.simulation_count, 0)
            self.assertTrue((project / "state.db").exists())
            self.assertTrue((project / "requirements" / "requirements_v2.json").exists())
            self.assertTrue((project / "architecture" / "candidate_architectures_v1.json").exists())
            status = project_status(project)
            self.assertEqual(status["tasks"]["blocked"], 1)

    def test_mock_run_is_labeled_and_checkpointed(self):
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / "project"
            result = run_design("Design a 2.45 GHz patch antenna", project, mode="mock", max_iterations=2)
            self.assertEqual(result.status, "completed")
            self.assertGreater(result.simulation_count, 0)
            report = (project / "final" / "final_report.md").read_text(encoding="utf-8")
            self.assertIn("MOCK_SIMULATION", report)
            checkpoint = json.loads((project / "optimization" / "checkpoint.json").read_text(encoding="utf-8"))
            self.assertEqual(checkpoint["status"], "completed")

    def test_text_fallback_remains_low_confidence_and_provenanced(self):
        with tempfile.TemporaryDirectory() as temp:
            paper = Path(temp) / "paper.pdf"
            paper.write_bytes(b"%PDF-1.4\nII RESULTS\nMeasured S11 = -15 dB at 2.45 GHz. eps_r = 4.4")
            data = PaperIngestionEngine(Path(temp) / "research").ingest_paper(paper)
            self.assertEqual(data["parser_status"], "raw_text_fallback_low_confidence")
            self.assertTrue(data["extracted_values"])
            self.assertTrue(all(item["confidence"] == 0.25 for item in data["extracted_values"]))
            self.assertTrue(any(item["evidence_type"] == "measured" for item in data["extracted_values"]))

    def test_openems_mode_generates_requested_family_without_fake_results(self):
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / "helix"
            result = run_design(
                "Design an axial-mode helix antenna at 2.45 GHz",
                project,
                mode="openems",
            )
            self.assertEqual(result.status, "openems_project_generated")
            self.assertEqual(result.selected_topology, "helix")
            self.assertEqual(result.simulation_count, 0)
            plan = json.loads(
                (project / "openems" / "openems_plan.json").read_text(
                    encoding="utf-8"
                )
            )
            validation = json.loads(
                (project / "final" / "validation_v1.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(plan["family"], "helix")
            self.assertFalse(validation["simulation_performed"])
            self.assertFalse((project / "openems" / "results.json").exists())

    def test_openems_simulate_records_real_solver_source_and_unmet_target(self):
        frequencies = [2.2e9 + i * 1e6 for i in range(501)]
        solver_result = {
            "source": "OPENEMS_FDTD", "frequency_hz": frequencies,
            "s11_db": [-1.0] * 501, "z_real_ohm": [20.0] * 501,
            "z_imag_ohm": [100.0] * 501, "best_s11_db": -1.0,
        }
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / "project"
            with patch(
                "prompt2cst.autonomous.execute_project",
                return_value={"result": solver_result, "results": str(project / "openems" / "results.json")},
            ) as solver:
                result = run_design(
                    "Design a 2.45 GHz PIFA with S11 < -10 dB",
                    project, mode="openems-simulate", max_iterations=1,
                )
            solver.assert_called_once()
            self.assertEqual(result.status, "openems_simulated")
            self.assertEqual(result.simulation_count, 1)
            validation = json.loads(Path(result.artifacts["validation"]).read_text(encoding="utf-8"))
            self.assertEqual(validation["status"], "TARGET_UNMET")
            self.assertTrue(validation["simulation_performed"])
            self.assertIn("Target met: no", (project / "final" / "final_report.md").read_text(encoding="utf-8"))
            proposal = json.loads(Path(result.artifacts["fabrication_proposal"]).read_text(encoding="utf-8"))
            self.assertEqual(proposal["status"], "GEOMETRY_PROPOSAL_NOT_FABRICATION_VALIDATED")
            self.assertIn(proposal["project_sha256"], (project / "final" / "final_report.md").read_text(encoding="utf-8"))
            self.assertTrue(Path(result.artifacts["fabrication_top_view"]).is_file())

    def test_openems_simulate_uses_better_real_pifa_search_result(self):
        frequencies = [2.2e9 + i * 1e6 for i in range(501)]
        initial = {
            "source": "OPENEMS_FDTD", "frequency_hz": frequencies,
            "s11_db": [-1.0] * 501, "z_real_ohm": [20.0] * 501,
            "z_imag_ohm": [100.0] * 501, "best_s11_db": -1.0,
        }
        optimized = {
            **initial, "s11_db": [-13.0] * 501,
            "z_real_ohm": [37.0] * 501, "z_imag_ohm": [11.0] * 501,
            "best_s11_db": -13.0,
        }
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / "project"
            candidate = project / "openems_search" / "candidate"

            def fake_search(*_args, **_kwargs):
                candidate.mkdir(parents=True)
                generated = write_project(
                    build_project("pifa", 2.45e9, pifa_length_scale=1.4, pifa_feed_fraction=0.12),
                    candidate,
                )
                (candidate / "results.json").write_text(json.dumps(optimized), encoding="utf-8")
                return {
                    "real_runs_this_call": 1,
                    "best": {
                        "center_s11_db": -13.0,
                        "results": str(candidate / "results.json"),
                        "project_sha256": generated["sha256"],
                    },
                }

            def fake_mesh_check(*_args, **_kwargs):
                refined = candidate / "mesh_refined_1.25"
                generated = write_project(
                    build_project(
                        "pifa", 2.45e9, pifa_length_scale=1.4,
                        pifa_feed_fraction=0.12, mesh_refinement_factor=1.875,
                    ), refined,
                )
                refined_result = {**optimized, "s11_db": [-12.0] * 501, "best_s11_db": -12.0}
                (refined / "results.json").write_text(json.dumps(refined_result), encoding="utf-8")
                return {
                    "status": "CONVERGED", "real_runs_this_call": 1,
                    "refined_results": str(refined / "results.json"),
                    "refined_project_sha256": generated["sha256"],
                }

            with patch(
                "prompt2cst.autonomous.execute_project",
                return_value={"result": initial, "results": str(project / "openems" / "results.json")},
            ), patch("prompt2cst.autonomous.search_pifa", side_effect=fake_search), patch(
                "prompt2cst.autonomous.verify_mesh_convergence", side_effect=fake_mesh_check,
            ):
                result = run_design(
                    "Design a 2.45 GHz PIFA with S11 < -10 dB",
                    project, mode="openems-simulate", max_iterations=3,
                )
            self.assertEqual(result.simulation_count, 3)
            measured = json.loads(Path(result.artifacts["simulation_result"]).read_text(encoding="utf-8"))
            self.assertTrue(measured["target_met"])
            self.assertEqual(measured["s11_db"], -12.0)
            validation = json.loads(Path(result.artifacts["validation"]).read_text(encoding="utf-8"))
            self.assertEqual(validation["status"], "TARGET_MET_MESH_CONVERGED")

    def test_openems_simulate_retries_nonconverged_mesh_within_budget(self):
        frequencies = [2.2e9 + i * 1e6 for i in range(501)]
        initial = {
            "source": "OPENEMS_FDTD", "frequency_hz": frequencies,
            "s11_db": [-12.0] * 501, "z_real_ohm": [45.0] * 501,
            "z_imag_ohm": [5.0] * 501, "best_s11_db": -12.0,
        }
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / "project"
            mesh_roots = []

            def fake_mesh_check(mesh_root, *, refinement_factor):
                mesh_root = Path(mesh_root)
                mesh_roots.append(mesh_root)
                plan = json.loads((mesh_root / "openems_plan.json").read_text(encoding="utf-8"))
                refined = mesh_root / "mesh_refined_1.25"
                generated = write_project(build_project(
                    "pifa", 2.45e9,
                    mesh_refinement_factor=plan["mesh_refinement_factor"] * refinement_factor,
                ), refined)
                s11 = -14.0 if len(mesh_roots) == 1 else -14.2
                (refined / "results.json").write_text(json.dumps({
                    **initial, "s11_db": [s11] * 501, "best_s11_db": s11,
                }), encoding="utf-8")
                (mesh_root / "mesh_convergence.json").write_text("{}", encoding="utf-8")
                return {
                    "status": "NOT_CONVERGED" if len(mesh_roots) == 1 else "CONVERGED",
                    "real_runs_this_call": 1,
                    "refined_results": str(refined / "results.json"),
                    "refined_project_sha256": generated["sha256"],
                }

            with patch(
                "prompt2cst.autonomous.execute_project",
                return_value={"result": initial, "results": str(project / "openems" / "results.json")},
            ), patch(
                "prompt2cst.autonomous.verify_mesh_convergence", side_effect=fake_mesh_check,
            ) as check:
                result = run_design(
                    "Design a 2.45 GHz PIFA with S11 < -10 dB",
                    project, mode="openems-simulate", max_iterations=3,
                )
            self.assertEqual(result.simulation_count, 3)
            self.assertEqual(check.call_count, 2)
            self.assertEqual(mesh_roots[1], mesh_roots[0] / "mesh_refined_1.25")
            validation = json.loads(Path(result.artifacts["validation"]).read_text(encoding="utf-8"))
            self.assertEqual(validation["status"], "TARGET_MET_MESH_CONVERGED")
            self.assertEqual(result.artifacts["mesh_convergence"], str(mesh_roots[1] / "mesh_convergence.json"))

    def test_openems_simulate_does_not_claim_success_after_failed_domain_check(self):
        frequencies = [2.2e9 + i * 1e6 for i in range(501)]
        initial = {
            "source": "OPENEMS_FDTD", "frequency_hz": frequencies,
            "s11_db": [-12.0] * 501, "z_real_ohm": [45.0] * 501,
            "z_imag_ohm": [5.0] * 501, "best_s11_db": -12.0,
        }
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / "project"

            def fake_mesh_check(mesh_root, *, refinement_factor):
                refined = Path(mesh_root) / "mesh_refined_1.25"
                generated = write_project(build_project(
                    "pifa", 2.45e9, mesh_refinement_factor=refinement_factor,
                ), refined)
                (refined / "results.json").write_text(json.dumps(initial), encoding="utf-8")
                return {
                    "status": "CONVERGED", "real_runs_this_call": 1,
                    "refined_results": str(refined / "results.json"),
                    "refined_project_sha256": generated["sha256"],
                }

            def fake_domain_check(domain_root, *, padding_factor):
                enlarged = Path(domain_root) / "domain_enlarged_1.25"
                plan = build_project("pifa", 2.45e9, mesh_refinement_factor=1.25)
                generated = write_project(plan.model_copy(update={
                    "simulation_box_mm": tuple(size * padding_factor for size in plan.simulation_box_mm),
                }), enlarged)
                lost = {**initial, "s11_db": [-8.0] * 501, "best_s11_db": -8.0}
                (enlarged / "results.json").write_text(json.dumps(lost), encoding="utf-8")
                (Path(domain_root) / "domain_convergence.json").write_text("{}", encoding="utf-8")
                return {
                    "status": "NOT_CONVERGED", "real_runs_this_call": 1,
                    "enlarged_results": str(enlarged / "results.json"),
                    "enlarged_project_sha256": generated["sha256"],
                }

            with patch(
                "prompt2cst.autonomous.execute_project",
                return_value={"result": initial, "results": str(project / "openems" / "results.json")},
            ), patch(
                "prompt2cst.autonomous.verify_mesh_convergence", side_effect=fake_mesh_check,
            ), patch(
                "prompt2cst.autonomous.verify_domain_convergence", side_effect=fake_domain_check,
            ) as domain_check:
                result = run_design(
                    "Design a 2.45 GHz PIFA with S11 < -10 dB",
                    project, mode="openems-simulate", max_iterations=3,
                )
            domain_check.assert_called_once()
            self.assertEqual(result.simulation_count, 3)
            validation = json.loads(Path(result.artifacts["validation"]).read_text(encoding="utf-8"))
            self.assertEqual(validation["status"], "DOMAIN_NOT_CONVERGED")
            self.assertFalse(validation["target_met"])
            self.assertEqual(validation["domain_convergence"], "NOT_CONVERGED")

    def test_openems_simulate_recovers_match_lost_on_refined_mesh(self):
        frequencies = [2.2e9 + i * 1e6 for i in range(501)]
        base = {
            "source": "OPENEMS_FDTD", "frequency_hz": frequencies,
            "z_real_ohm": [50.0] * 501, "z_imag_ohm": [0.0] * 501,
        }
        initial = {**base, "s11_db": [-12.0] * 501, "best_s11_db": -12.0}
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / "project"
            mesh_runs = []

            def fake_mesh_check(mesh_root, *, refinement_factor):
                mesh_root = Path(mesh_root)
                mesh_runs.append(mesh_root)
                plan = json.loads((mesh_root / "openems_plan.json").read_text(encoding="utf-8"))
                refined = mesh_root / "mesh_refined_1.25"
                generated = write_project(build_project(
                    "pifa", 2.45e9,
                    mesh_refinement_factor=plan["mesh_refinement_factor"] * refinement_factor,
                ), refined)
                s11 = -9.0 if len(mesh_runs) == 1 else -12.5
                (refined / "results.json").write_text(json.dumps({
                    **base, "s11_db": [s11] * 501, "best_s11_db": s11,
                }), encoding="utf-8")
                return {
                    "status": "CONVERGED", "real_runs_this_call": 1,
                    "refined_results": str(refined / "results.json"),
                    "refined_project_sha256": generated["sha256"],
                }

            def fake_recovery(_frequency_hz, recovery_dir, **kwargs):
                self.assertAlmostEqual(kwargs["mesh_refinement_factor"], 1.25)
                candidate = Path(recovery_dir) / "candidate"
                generated = write_project(build_project(
                    "pifa", 2.45e9, mesh_refinement_factor=1.25,
                    pifa_length_scale=1.02,
                ), candidate)
                (candidate / "results.json").write_text(json.dumps({
                    **base, "s11_db": [-13.0] * 501, "best_s11_db": -13.0,
                }), encoding="utf-8")
                return {
                    "real_runs_this_call": 1,
                    "best": {
                        "meets_target": True,
                        "results": str(candidate / "results.json"),
                        "project_sha256": generated["sha256"],
                    },
                }

            with patch(
                "prompt2cst.autonomous.execute_project",
                return_value={"result": initial, "results": str(project / "openems" / "results.json")},
            ), patch(
                "prompt2cst.autonomous.verify_mesh_convergence", side_effect=fake_mesh_check,
            ), patch(
                "prompt2cst.autonomous.search_pifa", side_effect=fake_recovery,
            ) as recovery:
                result = run_design(
                    "Design a 2.45 GHz PIFA with S11 < -10 dB",
                    project, mode="openems-simulate", max_iterations=4,
                )
            recovery.assert_called_once()
            self.assertEqual(len(mesh_runs), 2)
            self.assertEqual(result.simulation_count, 4)
            validation = json.loads(Path(result.artifacts["validation"]).read_text(encoding="utf-8"))
            self.assertEqual(validation["status"], "TARGET_MET_MESH_CONVERGED")
            self.assertTrue(validation["target_met"])

    def test_openems_simulate_reports_lost_target_and_nonconverged_mesh(self):
        frequencies = [2.2e9 + i * 1e6 for i in range(501)]
        initial = {
            "source": "OPENEMS_FDTD", "frequency_hz": frequencies,
            "s11_db": [-12.0] * 501, "z_real_ohm": [45.0] * 501,
            "z_imag_ohm": [5.0] * 501, "best_s11_db": -12.0,
        }
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / "project"

            def fake_mesh_check(mesh_root, *, refinement_factor):
                refined = Path(mesh_root) / "mesh_refined_1.25"
                generated = write_project(build_project(
                    "pifa", 2.45e9, mesh_refinement_factor=refinement_factor,
                ), refined)
                (refined / "results.json").write_text(json.dumps({
                    **initial, "s11_db": [-9.0] * 501, "best_s11_db": -9.0,
                }), encoding="utf-8")
                return {
                    "status": "NOT_CONVERGED", "real_runs_this_call": 1,
                    "refined_results": str(refined / "results.json"),
                    "refined_project_sha256": generated["sha256"],
                }

            with patch(
                "prompt2cst.autonomous.execute_project",
                return_value={"result": initial, "results": str(project / "openems" / "results.json")},
            ), patch(
                "prompt2cst.autonomous.verify_mesh_convergence", side_effect=fake_mesh_check,
            ):
                result = run_design(
                    "Design a 2.45 GHz PIFA with S11 < -10 dB",
                    project, mode="openems-simulate", max_iterations=2,
                )
            validation = json.loads(Path(result.artifacts["validation"]).read_text(encoding="utf-8"))
            self.assertEqual(validation["status"], "TARGET_UNMET_MESH_NOT_CONVERGED")
            self.assertFalse(validation["target_met"])

    def test_openems_simulate_retains_completed_result_after_mesh_timeout(self):
        frequencies = [2.2e9 + i * 1e6 for i in range(501)]
        initial = {
            "source": "OPENEMS_FDTD", "frequency_hz": frequencies,
            "s11_db": [-12.0] * 501, "z_real_ohm": [45.0] * 501,
            "z_imag_ohm": [5.0] * 501, "best_s11_db": -12.0,
        }
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / "project"
            with patch(
                "prompt2cst.autonomous.execute_project",
                return_value={"result": initial, "results": str(project / "openems" / "results.json")},
            ), patch(
                "prompt2cst.autonomous.verify_mesh_convergence",
                side_effect=subprocess.TimeoutExpired(cmd="openEMS", timeout=1200),
            ):
                result = run_design(
                    "Design a 2.45 GHz PIFA with S11 < -10 dB",
                    project, mode="openems-simulate", max_iterations=2,
                )
            self.assertEqual(result.simulation_count, 2)
            summary = json.loads(Path(result.artifacts["simulation_result"]).read_text(encoding="utf-8"))
            self.assertEqual(summary["s11_db"], -12.0)
            validation = json.loads(Path(result.artifacts["validation"]).read_text(encoding="utf-8"))
            self.assertEqual(validation["status"], "S11_THRESHOLD_MET_MESH_INCONCLUSIVE")
            self.assertEqual(validation["mesh_convergence"], "INCONCLUSIVE_TIMEOUT")
            self.assertTrue(Path(result.artifacts["mesh_convergence"]).is_file())

    def test_openems_simulate_accepts_inconclusive_mesh_report(self):
        frequencies = [2.2e9 + i * 1e6 for i in range(501)]
        initial = {
            "source": "OPENEMS_FDTD", "frequency_hz": frequencies,
            "s11_db": [-12.0] * 501, "z_real_ohm": [45.0] * 501,
            "z_imag_ohm": [5.0] * 501, "best_s11_db": -12.0,
        }
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / "project"
            with patch(
                "prompt2cst.autonomous.execute_project",
                return_value={"result": initial, "results": str(project / "openems" / "results.json")},
            ), patch(
                "prompt2cst.autonomous.verify_mesh_convergence",
                return_value={
                    "status": "INCONCLUSIVE_TIMEOUT", "real_runs_this_call": 1,
                    "refined_results": None,
                },
            ):
                result = run_design(
                    "Design a 2.45 GHz PIFA with S11 < -10 dB",
                    project, mode="openems-simulate", max_iterations=2,
                )
            summary = json.loads(Path(result.artifacts["simulation_result"]).read_text(encoding="utf-8"))
            self.assertEqual(summary["s11_db"], -12.0)
            self.assertEqual(summary["mesh_convergence"], "INCONCLUSIVE_TIMEOUT")


if __name__ == "__main__":
    unittest.main()
