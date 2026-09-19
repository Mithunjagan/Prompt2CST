import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from prompt2cst.real_pifa_sweep import RealPifaImpedanceSweep


class RealPifaSweepTests(unittest.TestCase):
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
