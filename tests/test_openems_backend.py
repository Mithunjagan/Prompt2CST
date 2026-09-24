from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from prompt2cst.openems_backend import (
    _validate_solver_convergence,
    OpenEMSProject,
    backend_status,
    build_project,
    pifa_dimensions,
    render_python,
    sampled_s11_band,
    write_project,
    execute_project,
    search_pifa,
    validate_result,
    verify_mesh_convergence,
)


class OpenEMSBackendTests(unittest.TestCase):
    def test_all_advanced_families_generate_valid_projects(self) -> None:
        for family in ("pifa", "helix", "yagi", "horn", "vivaldi"):
            with self.subTest(family=family):
                project = build_project(family, 2.45e9)
                self.assertGreater(len(project.primitives), 1)
                self.assertEqual(len(project.canonical_sha256), 64)
                self.assertEqual(project.solver_recipe_version, "openems-fdtd-v2")
                self.assertTrue(project.verification_required)
                self.assertTrue(project.source_urls)

    def test_family_specific_geometry_and_ports(self) -> None:
        helix = build_project("helix", 2.45e9)
        self.assertIn("curve", {item.kind for item in helix.primitives})
        horn = build_project("horn", 15e9)
        self.assertEqual(horn.port.kind, "rect_waveguide")
        vivaldi = build_project("vivaldi", 3e9)
        self.assertIn("substrate", {item.material for item in vivaldi.primitives})
        yagi = build_project("yagi", 915e6)
        self.assertEqual(next(p for p in yagi.primitives if p.name == "boom").material, "fiberglass")
        first_strip = next(p for p in vivaldi.primitives if p.name == "lower_0")
        self.assertEqual(vivaldi.port.start[1], first_strip.stop[1])

    def test_pifa_parameters_change_the_plan_and_reject_other_families(self) -> None:
        baseline = build_project("pifa", 2.45e9)
        tuned = build_project("pifa", 2.45e9, pifa_length_scale=1.2, pifa_feed_fraction=0.7)
        self.assertNotEqual(baseline.canonical_sha256, tuned.canonical_sha256)
        self.assertGreater(tuned.port.start[0], baseline.port.start[0])
        dimensions = pifa_dimensions(tuned)
        self.assertGreater(dimensions["radiator_length_mm"], pifa_dimensions(baseline)["radiator_length_mm"])
        self.assertGreater(dimensions["feed_clearance_from_short_wall_mm"], 0)
        with self.assertRaisesRegex(ValueError, "require family=pifa"):
            build_project("helix", 2.45e9, pifa_feed_fraction=0.7)

    def test_rendered_script_uses_official_port_and_result_api(self) -> None:
        script = render_python(build_project("pifa", 2.45e9))
        self.assertIn("AddLumpedPort", script)
        self.assertIn("CalcPort", script)
        self.assertIn("OPENEMS_FDTD", script)
        self.assertIn("F0 / 2", script)
        self.assertIn("NrTS=30000", script)
        self.assertIn("sx/20, sy/20, sz/20", script)
        compile(script, "run_openems.py", "exec")

    def test_write_project_is_deterministic_and_inspectable(self) -> None:
        project = build_project("yagi", 915e6)
        with tempfile.TemporaryDirectory() as tmp:
            first = write_project(project, tmp)
            second = write_project(project, tmp)
            self.assertEqual(first["sha256"], second["sha256"])
            plan = json.loads(Path(first["plan"]).read_text(encoding="utf-8"))
            self.assertEqual(plan["family"], "yagi_uda")
            self.assertTrue(Path(first["script"]).is_file())

    def test_missing_solver_is_reported_without_mocking_results(self) -> None:
        status = backend_status()
        self.assertIn(status["status"], {"READY", "BACKEND_UNAVAILABLE"})
        self.assertNotIn("results", status)

    def test_far_field_is_explicit_and_disk_run_is_guarded(self) -> None:
        self.assertFalse(build_project("pifa", 2.45e9).nf2ff)
        far_field_project = build_project("pifa", 2.45e9, include_far_field=True)
        self.assertTrue(far_field_project.nf2ff)
        script = render_python(far_field_project)
        self.assertIn("CalcNF2FF", script)
        self.assertIn("port.P_acc", script)
        compile(script, "run_openems.py", "exec")
        with tempfile.TemporaryDirectory() as tmp:
            write_project(build_project("pifa", 2.45e9), tmp)
            with patch(
                "prompt2cst.openems_backend.backend_status",
                return_value={"available": True},
            ):
                with self.assertRaisesRegex(RuntimeError, "DISK_PREFLIGHT"):
                    execute_project(tmp, minimum_free_bytes=10**18)

    def test_execution_rejects_a_modified_generated_script(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = write_project(build_project("pifa", 2.45e9), tmp)
            Path(paths["script"]).write_text(
                "print('untrusted replacement')\n", encoding="utf-8"
            )
            with self.assertRaisesRegex(RuntimeError, "SCRIPT_HASH_MISMATCH"):
                execute_project(tmp, minimum_free_bytes=0)

    def test_timeout_keeps_solver_log_and_terminates_process_tree(self) -> None:
        class HungSolver:
            pid = 12345

            def communicate(self, timeout=None):
                if timeout is not None:
                    raise subprocess.TimeoutExpired(cmd="openEMS", timeout=timeout)
                return None, None

        with tempfile.TemporaryDirectory() as tmp:
            write_project(build_project("pifa", 2.45e9), tmp)
            with (
                patch("prompt2cst.openems_backend.backend_status", return_value={"available": True}),
                patch("prompt2cst.openems_backend.subprocess.Popen", return_value=HungSolver()) as runner,
                patch("prompt2cst.openems_backend.subprocess.run") as taskkill,
                patch("prompt2cst.openems_backend.os.killpg", create=True) as killpg,
            ):
                with self.assertRaises(subprocess.TimeoutExpired):
                    execute_project(tmp, timeout_seconds=1, minimum_free_bytes=0)
            self.assertTrue((Path(tmp) / "solver.log").is_file())
            self.assertEqual(runner.call_args.kwargs["stderr"], subprocess.STDOUT)
            if os.name == "nt":
                taskkill.assert_called_once()
            else:
                killpg.assert_called_once()

    def test_solver_must_reach_energy_decay_criterion(self) -> None:
        log_path = Path("solver.log")
        _validate_solver_convergence(
            "[@ 20s] Timestep: 5661 || Energy: ~1e-18 (-42.28dB)", log_path
        )
        with self.assertRaisesRegex(RuntimeError, "OPENEMS_NOT_CONVERGED"):
            _validate_solver_convergence(
                "[@ 20s] Timestep: 30000 || Energy: ~1e-18 (-21.02dB)", log_path
            )
        with self.assertRaisesRegex(RuntimeError, "OPENEMS_NOT_CONVERGED"):
            _validate_solver_convergence("solver omitted energy output", log_path)

    def test_sampled_match_band_stays_contiguous_around_target(self) -> None:
        frequencies = [800e6 + i * 272000 for i in range(501)]
        s11 = [-2.0] * 501
        for index in list(range(240, 261)) + list(range(300, 311)):
            s11[index] = -12.0
        result = {"frequency_hz": frequencies, "s11_db": s11}
        band = sampled_s11_band(result, 868e6)
        self.assertEqual(band["sampled_lower_hz"], frequencies[240])
        self.assertEqual(band["sampled_upper_hz"], frequencies[260])
        self.assertEqual(band["sampled_bandwidth_hz"], 5_440_000)
        self.assertFalse(band["upper_edge_outside_sweep"])
        s11[250] = -2.0
        self.assertIsNone(sampled_s11_band(result, 868e6))
        with self.assertRaisesRegex(ValueError, "within the sampled sweep"):
            sampled_s11_band(result, 700e6)

    def test_execution_rejects_a_stale_result_file(self) -> None:
        class ExitedSolver:
            returncode = 0

            def communicate(self, timeout=None):
                return None, None

        with tempfile.TemporaryDirectory() as tmp:
            write_project(build_project("pifa", 2.45e9), tmp)
            (Path(tmp) / "results.json").write_text("{}", encoding="utf-8")
            with (
                patch("prompt2cst.openems_backend.backend_status", return_value={"available": True}),
                patch("prompt2cst.openems_backend.subprocess.Popen", return_value=ExitedSolver()),
                patch("prompt2cst.openems_backend._validate_solver_convergence"),
            ):
                with self.assertRaisesRegex(RuntimeError, "without fresh results.json"):
                    execute_project(tmp, minimum_free_bytes=0)

    def test_rejects_nonfinite_and_wrong_plan_solver_results(self) -> None:
        project = build_project("pifa", 2.45e9)
        frequencies = [project.frequency_min_hz + i * (project.frequency_max_hz - project.frequency_min_hz) / 500 for i in range(501)]
        result = {
            "source": "OPENEMS_FDTD", "project_sha256": project.canonical_sha256,
            "frequency_hz": frequencies, "s11_db": [-3.0] * 501,
            "z_real_ohm": [50.0] * 501, "z_imag_ohm": [0.0] * 501,
            "best_frequency_hz": frequencies[0], "best_s11_db": -3.0,
        }
        validate_result(result, project)
        result["s11_db"][4] = float("nan")
        with self.assertRaisesRegex(RuntimeError, "nonfinite"):
            validate_result(result, project)
        result["s11_db"][4] = -3.0
        result["project_sha256"] = "wrong"
        with self.assertRaisesRegex(RuntimeError, "PLAN_MISMATCH"):
            validate_result(result, project)
        far_project = build_project("pifa", 2.45e9, include_far_field=True)
        result["project_sha256"] = far_project.canonical_sha256
        with self.assertRaisesRegex(RuntimeError, "missing far-field"):
            validate_result(result, far_project)

    def test_pifa_search_ranks_solver_results_and_resumes(self) -> None:
        def fake_execute(candidate_dir, **_kwargs):
            root = Path(candidate_dir)
            project = OpenEMSProject.model_validate_json(
                (root / "openems_plan.json").read_text(encoding="utf-8")
            )
            frequencies = [project.frequency_min_hz + i * (project.frequency_max_hz - project.frequency_min_hz) / 500 for i in range(501)]
            match = -12.0 if project.port.start[0] >= 0 else -2.0
            result = {
                "source": "OPENEMS_FDTD", "project_sha256": project.canonical_sha256,
                "frequency_hz": frequencies, "s11_db": [match] * 501,
                "z_real_ohm": [50.0] * 501, "z_imag_ohm": [0.0] * 501,
                "best_frequency_hz": frequencies[0], "best_s11_db": match,
            }
            (root / "results.json").write_text(json.dumps(result), encoding="utf-8")
            return {"result": result}

        with tempfile.TemporaryDirectory() as tmp:
            with patch("prompt2cst.openems_backend.execute_project", side_effect=fake_execute) as runner:
                summary = search_pifa(
                    2.45e9, tmp, length_scales=(1.0,),
                    feed_fractions=(0.22, 0.5), max_runs=2,
                )
            self.assertEqual(runner.call_count, 2)
            self.assertEqual(summary["status"], "TARGET_MET")
            self.assertEqual(summary["best"]["feed_fraction"], 0.5)
            with patch("prompt2cst.openems_backend.execute_project") as runner:
                resumed = search_pifa(
                    2.45e9, tmp, length_scales=(1.0,),
                    feed_fractions=(0.22, 0.5), max_runs=2,
                )
            runner.assert_not_called()
            self.assertEqual(resumed["real_runs_this_call"], 0)

    def test_pifa_search_rejects_concurrent_use_of_same_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            def nested_search(*_args, **_kwargs):
                with self.assertRaisesRegex(RuntimeError, "ALREADY_RUNNING"):
                    search_pifa(2.45e9, tmp, max_runs=1)
                return {"status": "LOCKED"}

            with patch("prompt2cst.openems_backend._search_pifa_unlocked", side_effect=nested_search):
                self.assertEqual(search_pifa(2.45e9, tmp, max_runs=1)["status"], "LOCKED")

    def test_pifa_search_moves_off_target_resonance_toward_target(self) -> None:
        def fake_execute(candidate_dir, **_kwargs):
            root = Path(candidate_dir)
            project = OpenEMSProject.model_validate_json(
                (root / "openems_plan.json").read_text(encoding="utf-8")
            )
            frequencies = [project.frequency_min_hz + i * (project.frequency_max_hz - project.frequency_min_hz) / 500 for i in range(501)]
            length = next(p for p in project.primitives if p.name == "radiator")
            is_corrected = length.stop[0] - length.start[0] > 19.8
            s11 = [-12.0] * 501 if is_corrected else [-2.0] * 501
            if not is_corrected:
                s11[300] = -15.0
            best_index = min(range(501), key=lambda i: s11[i])
            result = {
                "source": "OPENEMS_FDTD", "project_sha256": project.canonical_sha256,
                "frequency_hz": frequencies, "s11_db": s11,
                "z_real_ohm": [50.0] * 501, "z_imag_ohm": [0.0] * 501,
                "best_frequency_hz": frequencies[best_index], "best_s11_db": s11[best_index],
            }
            (root / "results.json").write_text(json.dumps(result), encoding="utf-8")
            return {"result": result}

        with tempfile.TemporaryDirectory() as tmp:
            with patch("prompt2cst.openems_backend.execute_project", side_effect=fake_execute):
                summary = search_pifa(
                    2.45e9, tmp, length_scales=(1.0,),
                    feed_fractions=(0.22,), max_runs=2,
                )
            self.assertEqual(summary["status"], "TARGET_MET")
            self.assertEqual(summary["evaluated_candidates"], 2)
            self.assertGreater(summary["candidates"][1]["length_scale"], 1.0)

    def test_mesh_check_marks_large_solver_change_unconverged(self) -> None:
        def fake_execute(candidate_dir, **_kwargs):
            root = Path(candidate_dir)
            project = OpenEMSProject.model_validate_json(
                (root / "openems_plan.json").read_text(encoding="utf-8")
            )
            frequencies = [project.frequency_min_hz + i * (project.frequency_max_hz - project.frequency_min_hz) / 500 for i in range(501)]
            s11 = -12.0 if project.mesh_refinement_factor == 1.0 else -8.0
            result = {
                "source": "OPENEMS_FDTD", "project_sha256": project.canonical_sha256,
                "frequency_hz": frequencies, "s11_db": [s11] * 501,
                "z_real_ohm": [50.0] * 501, "z_imag_ohm": [0.0] * 501,
                "best_frequency_hz": frequencies[0], "best_s11_db": s11,
            }
            (root / "results.json").write_text(json.dumps(result), encoding="utf-8")
            return {"result": result}

        with tempfile.TemporaryDirectory() as tmp:
            write_project(build_project("pifa", 2.45e9), tmp)
            with patch("prompt2cst.openems_backend.execute_project", side_effect=fake_execute) as runner:
                report = verify_mesh_convergence(tmp)
            self.assertEqual(runner.call_count, 2)
            self.assertEqual(report["status"], "NOT_CONVERGED")
            self.assertAlmostEqual(report["s11_delta_db"], 4.0)
            self.assertNotEqual(report["baseline_project_sha256"], report["refined_project_sha256"])

    def test_mesh_check_records_inconclusive_timeout_without_losing_baseline(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = build_project("pifa", 2.45e9)
            write_project(project, tmp)
            frequencies = [
                project.frequency_min_hz + i * (project.frequency_max_hz - project.frequency_min_hz) / 500
                for i in range(501)
            ]
            baseline = {
                "source": "OPENEMS_FDTD", "project_sha256": project.canonical_sha256,
                "frequency_hz": frequencies, "s11_db": [-12.0] * 501,
                "z_real_ohm": [45.0] * 501, "z_imag_ohm": [5.0] * 501,
                "best_frequency_hz": frequencies[0], "best_s11_db": -12.0,
            }
            (Path(tmp) / "results.json").write_text(json.dumps(baseline), encoding="utf-8")
            with patch(
                "prompt2cst.openems_backend.execute_project",
                side_effect=subprocess.TimeoutExpired(cmd="openEMS", timeout=1200),
            ) as runner:
                report = verify_mesh_convergence(tmp)
            runner.assert_called_once()
            self.assertEqual(report["status"], "INCONCLUSIVE_TIMEOUT")
            self.assertIsNone(report["refined_results"])
            self.assertTrue((Path(tmp) / "results.json").is_file())
            self.assertEqual(
                json.loads((Path(tmp) / "mesh_convergence.json").read_text(encoding="utf-8"))["status"],
                "INCONCLUSIVE_TIMEOUT",
            )

    def test_rejects_unsupported_family(self) -> None:
        with self.assertRaisesRegex(ValueError, "unsupported openEMS family"):
            build_project("magic antenna", 2.45e9)


if __name__ == "__main__":
    unittest.main()
