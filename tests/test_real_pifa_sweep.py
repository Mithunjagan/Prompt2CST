import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from prompt2cst.real_pifa_sweep import (
    RESULT_EXTRACTION_TIMEOUT_SECONDS,
    RealPifaImpedanceSweep,
)


def _large_payload_worker(queue, _output_dir, _operation, _project_path, _kwargs, _trace_path):
    queue.put({"status": "completed", "result": {"samples": list(range(250_000))}})


class RealPifaSweepTests(unittest.TestCase):
    def test_bounded_com_drains_large_result_before_join(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "working_project.cst"
            project.write_text("mock", encoding="utf-8")
            sweep = RealPifaImpedanceSweep(root)
            with patch("prompt2cst.real_pifa_sweep._bounded_com_worker", _large_payload_worker):
                result = sweep._com_call("extract_results", project, timeout_seconds=10.0)
            self.assertEqual(len(result["samples"]), 250_000)
            sweep.cache.close()

    def test_live_candidate_uses_extended_result_extraction_timeout(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "working_project.cst"
            project.write_text("mock", encoding="utf-8")
            sweep = RealPifaImpedanceSweep(root, use_bounded_com=False)
            calls = []

            def com_call(operation, _path, **kwargs):
                calls.append((operation, kwargs.get("timeout_seconds")))
                if operation == "update_parameters":
                    return {"status": "completed", "updated": True}
                if operation == "read_parameter":
                    return kwargs["name"] == "radiator_length_mm" and 21.75 or 0.25
                if operation == "run_solver":
                    return {"status": "completed", "solver_run": True}
                raw = {}
                for suffix, key in ((".txt", "ascii_path"), (".s1p", "touchstone_path"), (".json", "raw_results_path")):
                    artifact = root / f"result{suffix}"
                    artifact.write_text("mock", encoding="utf-8")
                    raw[key] = str(artifact)
                return {"status": "completed", "extracted": {
                    "s11_db": (-15.0, "dB"), "f_res_ghz": (2.45, "GHz"), "vswr": (1.4, "1"),
                    "zin_re": (50.0, "Ohm"), "zin_im": (0.0, "Ohm"),
                }, "raw_extracted": raw, "unavailable": []}

            sweep._com_call = com_call
            sweep._run_live(project, 21.75, 0.25, "candidate")
            self.assertIn(("extract_results", RESULT_EXTRACTION_TIMEOUT_SECONDS), calls)
            sweep.cache.close()

    def test_resume_quarantines_project_after_cst_save_failure(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "checkpoint.json").write_text(json.dumps({
                "status": "blocked_cst_com",
                "blocker": {
                    "operation": "update_parameters",
                    "error": "Saving of C:\\\\p2cst\\\\working.cst failed.",
                },
            }), encoding="utf-8")
            sweep = RealPifaImpedanceSweep(root, resume=True, use_bounded_com=False)
            with self.assertRaisesRegex(RuntimeError, "CST_RESTART_REQUIRED"):
                sweep.run()
            sweep.cache.close()

    def _bridge(self, sweep, root):
        calls = []
        project = root / "working_project.cst"
        parameters = {"radiator_length_mm": 21.75, "feed_offset_mm": 0.5}
        def update(_path, params=None, **kwargs):
            params = params or kwargs["parameters"]
            calls.append(params["feed_offset_mm"])
            parameters.update(params)
            return {"status": "completed", "updated": True}
        def solve(_path): return {"status": "completed", "solver_run": True}
        def extract(_path, artifact_tag=""):
            offset = parameters["feed_offset_mm"]
            raw = {}
            for suffix, key in ((".txt", "ascii_path"), (".s1p", "touchstone_path"), (".json", "raw_results_path")):
                artifact = root / f"{artifact_tag}{suffix}"
                artifact.write_text("mock", encoding="utf-8")
                raw[key] = str(artifact)
            # Deliberately worse at 3 mm, better near 1 mm.
            return {"status": "completed", "extracted": {
                "s11_db": (-15.0, "dB"), "f_res_ghz": (2.45, "GHz"), "vswr": (1.4, "1"),
                "zin_re": (50.0 - abs(offset - 1.0), "Ohm"), "zin_im": (offset - 1.0, "Ohm"),
                "frequency_samples": ([2.45], "GHz"),
            }, "raw_extracted": raw, "unavailable": []}
        def read_param(_path, name):
            if Path(_path).name == "stage_a.cst":
                return {"radiator_length_mm": 21.75, "feed_offset_mm": 0.5}[name]
            return parameters[name]
        def create_snapshot(_source, _name=None, **_kwargs):
            # Create a mock snapshot file
            name = _name or _kwargs["snapshot_name"]
            snapshot_path = root / "snapshots" / name / f"{name}.cst"
            snapshot_path.parent.mkdir(parents=True, exist_ok=True)
            snapshot_path.write_text("mock snapshot", encoding="utf-8")
            return {"status": "VALID", "snapshot_path": str(snapshot_path), "validation": {"result_readback": {"status": "completed"}, "parameter_readback": dict(parameters)}}
        sweep.bridge.update_parameters = update
        sweep.bridge.run_solver = solve
        sweep.bridge.extract_results = extract
        sweep.bridge.read_parameter = read_param
        sweep.bridge.create_validated_cst_snapshot = create_snapshot
        return calls

    def test_interrupted_sweep_resumes_and_keeps_cache(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "stage_a.cst"
            source.write_text("stage-a", encoding="utf-8")
            stage_a = root / "stage_a_checkpoint.json"
            stage_a.write_text(json.dumps({"status": "FREQUENCY_LOCKED", "acceptance": {"frequency_locked": True},
                "best_parameters": {"radiator_length_mm": 21.75, "feed_offset_mm": 0.5},
                "final_snapshot": {"snapshot_path": str(source)}}), encoding="utf-8")
            sweep = RealPifaImpedanceSweep(root, stage_a_checkpoint=stage_a, use_bounded_com=False)
            calls = self._bridge(sweep, root)
            stopped = sweep.run(stop_after=2)
            self.assertEqual(stopped["status"], "interrupted")
            self.assertEqual(stopped["iteration"], 2)
            checkpoint = json.loads((root / "checkpoint.json").read_text())
            self.assertIn("optimizer_state", checkpoint)
            self.assertIn("completed_simulation_ids", checkpoint)
            resumed = RealPifaImpedanceSweep(root, resume=True, stage_a_checkpoint=stage_a, use_bounded_com=False)
            resumed.bridge = sweep.bridge
            state = resumed.run()
            self.assertEqual(state["status"], "completed")
            self.assertTrue(state["acceptance"]["improved"])
            self.assertTrue(Path(state["working_snapshot"]["snapshot_path"]).exists())
            self.assertTrue(Path(state["final_snapshot"]["snapshot_path"]).exists())
            self.assertEqual(len(state["history"]), 6)
            self.assertEqual(state["history"][0]["source"], "CST_SIMULATION")
            self.assertGreaterEqual(len(calls), 7)  # candidates plus final CST validation
            sweep.cache.close()
            resumed.cache.close()


if __name__ == "__main__":
    unittest.main()
