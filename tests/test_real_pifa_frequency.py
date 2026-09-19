import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from prompt2cst.real_pifa_frequency import RealPifaFrequencyOptimization


class RealPifaFrequencyTests(unittest.TestCase):
    def _bridge(self, optimizer: RealPifaFrequencyOptimization, root: Path):
        calls: list[dict[str, float]] = []
        project = root / "working_project.cst"

        def build(*_args, **_kwargs):
            project.write_text("project", encoding="utf-8")
            return {"project_path": str(project)}
        def update(_path, params):
            calls.append(dict(params)); return {"status": "completed"}
        def read(_path, name): return calls[-1][name]
        def solve(_path): return {"status": "completed"}
        def extract(_path, artifact_tag=""):
            length = calls[-1]["radiator_length_mm"]
            # A deterministic response that proves the real-loop control policy:
            # shortening the radiator raises resonance toward 2.45 GHz.
            f_res = 2.45 - (length - 23.0) * 0.05
            return {"status": "completed", "extracted": {
                "s11_db": (-15.0, "dB"), "f_res_ghz": (f_res, "GHz"), "vswr": (1.4, "1"),
                "zin_re": (45.0, "Ohm"), "zin_im": (-10.0, "Ohm"),
            }, "raw_extracted": {}, "unavailable": []}
        def snapshot(_source, name, **_kwargs):
            path = root / "snapshots" / name / f"{name}.cst"
            path.parent.mkdir(parents=True, exist_ok=True); path.write_text("snapshot", encoding="utf-8")
            return {"status": "VALID", "snapshot_path": str(path)}

        optimizer.bridge.build_temple_pifa = build
        optimizer.bridge.update_parameters = update
        optimizer.bridge.read_parameter = read
        optimizer.bridge.run_solver = solve
        optimizer.bridge.extract_results = extract
        optimizer.bridge.create_validated_cst_snapshot = snapshot
        return calls

    def test_stage_a_uses_only_radiator_as_active_and_locks_frequency(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            optimizer = RealPifaFrequencyOptimization(root)
            calls = self._bridge(optimizer, root)
            state = optimizer.run()
            self.assertEqual(state["status"], "FREQUENCY_LOCKED")
            self.assertTrue(state["acceptance"]["improved"])
            self.assertEqual(state["parameter_states"]["feed_offset_mm"], "FROZEN")
            self.assertEqual(state["parameter_states"]["radiator_length_mm"], "FROZEN")
            self.assertLess(state["final_validation"]["frequency_error_ghz"], 0.01)
            self.assertLess(state["sensitivity_analysis"]["df_res_dlength_ghz_per_mm"], 0)
            self.assertTrue(all(call["feed_offset_mm"] == 0.5 for call in calls))
            self.assertTrue((root / "final_parameters.json").exists())
            self.assertEqual(json.loads((root / "checkpoint.json").read_text())["status"], "FREQUENCY_LOCKED")
            optimizer.cache.close()

    def test_interruption_is_checkpointed_and_resume_does_not_rebuild(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            first = RealPifaFrequencyOptimization(root)
            calls = self._bridge(first, root)
            stopped = first.run(stop_after=3)
            self.assertEqual(stopped["status"], "interrupted")
            resumed = RealPifaFrequencyOptimization(root, resume=True)
            resumed.bridge = first.bridge
            state = resumed.run()
            self.assertEqual(state["status"], "FREQUENCY_LOCKED")
            self.assertGreaterEqual(len(calls), 5)
            first.cache.close(); resumed.cache.close()

    def test_resume_after_partial_sensitivity_does_not_duplicate_delta(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            first = RealPifaFrequencyOptimization(root)
            calls = self._bridge(first, root)
            original = first._evaluate
            def stop_after_minus(state, length, tag):
                record = original(state, length, tag)
                if length == 27.0:
                    raise RuntimeError("simulated interruption after minus delta")
                return record
            first._evaluate = stop_after_minus
            with self.assertRaisesRegex(RuntimeError, "simulated interruption"):
                first.run()
            resumed = RealPifaFrequencyOptimization(root, resume=True)
            resumed.bridge = first.bridge
            state = resumed.run()
            lengths = [record["parameters"]["radiator_length_mm"] for record in state["history"]]
            self.assertEqual(lengths.count(27.0), 1)
            self.assertLess(state["sensitivity_analysis"]["df_res_dlength_ghz_per_mm"], 0)
            first.cache.close(); resumed.cache.close()

    def test_local_refinement_keeps_feed_frozen_and_records_local_direction(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            optimizer = RealPifaFrequencyOptimization(root)
            calls = self._bridge(optimizer, root)
            state = optimizer.run()
            state["status"] = "PARTIAL_FREQUENCY_IMPROVEMENT"
            state["parameter_states"]["radiator_length_mm"] = "CONSTRAINED"
            optimizer._checkpoint(state)
            refined = optimizer.run_local_refinement()
            self.assertIn("local_refinement", refined)
            self.assertIn("local_direction", refined["local_refinement"])
            self.assertEqual(refined["parameter_states"]["feed_offset_mm"], "FROZEN")
            self.assertTrue(all(call["feed_offset_mm"] == 0.5 for call in calls))
            optimizer.cache.close()


if __name__ == "__main__":
    unittest.main()
