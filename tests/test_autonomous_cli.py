from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from prompt2cst.autonomous import project_status, run_design
from prompt2cst.papers import PaperIngestionEngine


class AutonomousWorkflowTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
