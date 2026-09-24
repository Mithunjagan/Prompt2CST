from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from zipfile import ZipFile

from prompt2cst.autonomous import run_design
from prompt2cst.datasets import FacultyDataset


def _sweep(parameters: str, values: list[tuple[float, float]]) -> str:
    rows = [f"{frequency}\t{magnitude}" for frequency, magnitude in values]
    return "\n".join([f"#Parameters = {{{parameters}}}", '#"Frequency / GHz"\t"S1,1 [Magnitude / dB]"', "#---", *rows])


class FacultyDatasetTests(unittest.TestCase):
    def _archive(self, root: Path) -> Path:
        path = root / "faculty.zip"
        with ZipFile(path, "w") as archive:
            archive.writestr("dataset/design_001.txt", _sweep("a=1; b=2", [(1.0, -2.0), (2.0, -15.0), (3.0, -4.0)]))
            archive.writestr("dataset/design_002.txt", _sweep("a=2; b=2", [(1.0, -3.0), (2.0, -8.0), (3.0, -20.0)]))
        return path

    def test_ingests_ranks_and_preserves_provenance(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            dataset = FacultyDataset.load(self._archive(root))
            summary = dataset.analyze(2.0)
            self.assertEqual(summary["design_count"], 2)
            self.assertEqual(summary["fixed_parameters"], {"b": 2.0})
            self.assertEqual(summary["target_ranking"][0]["source_entry"], "dataset/design_001.txt")
            self.assertEqual(summary["target_assessment"]["status"], "SUPPORTED_BY_DATASET")
            self.assertIn("a", summary["one_factor_sensitivity"])
            self.assertEqual(summary["manufacturing_use"], "BLOCKED_MISSING_GEOMETRY_PARAMETER_MAP")
            paths = dataset.save_study(root / "study", 2.0)
            self.assertTrue(Path(paths["normalized_sweeps"]).is_file())

    def test_rejects_unsafe_archive_path(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "unsafe.zip"
            with ZipFile(path, "w") as archive:
                archive.writestr("../design.txt", _sweep("a=1", [(1.0, -1.0), (2.0, -2.0)]))
            with self.assertRaisesRegex(ValueError, "Unsafe dataset entry path"):
                FacultyDataset.load(path)

    def test_autonomous_project_records_dataset_evidence(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project"
            run_design(
                "Design an antenna at 2 GHz",
                project,
                mode="dry-run",
                datasets=[self._archive(root)],
            )
            evidence_path = project / "research" / "evidence_v1.json"
            evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
            self.assertEqual(evidence["datasets"][0]["design_count"], 2)
            self.assertEqual(
                evidence["datasets"][0]["manufacturing_use"],
                "BLOCKED_MISSING_GEOMETRY_PARAMETER_MAP",
            )


if __name__ == "__main__":
    unittest.main()
