"""Tests for zero-cost RF swarm infrastructure: CostGuard, ModelRouter, SharedState, Orchestrator, Papers, Evidence, Architect, Wearable."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from prompt2cst.architect import RFArchitectureAgent
from prompt2cst.cost_guard import CostGuard, ZeroCostViolationError
from prompt2cst.evidence import EvidenceDatabase
from prompt2cst.model_router import ModelRouter, AgentRole
from prompt2cst.orchestrator import ChiefOrchestrator
from prompt2cst.papers import PaperIngestionEngine
from prompt2cst.shared_state import ProjectWorkspace
from prompt2cst.wearable import WearableAntennaEvaluator


class TestZeroCostSwarm(unittest.TestCase):
    def test_cost_guard(self):
        guard = CostGuard()
        report = guard.to_dict()
        self.assertEqual(report["total_cost_usd"], 0.0)
        self.assertEqual(report["total_cost_inr"], 0.0)

        # Ensure forbidden key check raises ZeroCostViolationError if key is set
        try:
            os.environ["OPENAI_API_KEY"] = "sk-fake-key"
            with self.assertRaises(ZeroCostViolationError):
                guard.verify_no_paid_keys()
        finally:
            os.environ.pop("OPENAI_API_KEY", None)

    def test_model_router(self):
        router = ModelRouter()
        spec = router.route(AgentRole.RF_ARCHITECT, {"task": "Select best antenna topology for 2.45 GHz"})
        self.assertIn(spec.mode, ["builtin", "needs_agent", "local_ollama"])
        self.assertEqual(spec.cost_usd, 0.0)

    def test_shared_state_db(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir)
            workspace = ProjectWorkspace(db_path)
            workspace.initialize()
            workspace.save_metadata("SmartGlasses", {"freq": 2.45e9})
            meta = workspace.load_metadata("SmartGlasses")
            self.assertEqual(meta["freq"], 2.45e9)
            workspace.close()

    def test_paper_ingestion_and_evidence(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            pdf_path = Path(tmpdir) / "sample_paper.pdf"
            pdf_path.write_bytes(b"%PDF-1.4 sample paper text with f0 = 2.45 GHz, S11 = -15 dB, Substrate FR4 eps_r = 4.4")

            engine = PaperIngestionEngine(research_dir=Path(tmpdir))
            extracted = engine.ingest_paper(pdf_path)
            self.assertIsNotNone(extracted.get("extracted_parameters"))

            db = EvidenceDatabase(Path(tmpdir) / "evidence.db")
            count = db.add_paper_claims(extracted)
            self.assertGreaterEqual(count, 0)
            db.close()

    def test_rf_architect_agent(self):
        agent = RFArchitectureAgent()
        reqs = {
            "center_frequency_hz": 2.45e9,
            "frequency_min_hz": 2.4e9,
            "frequency_max_hz": 2.5e9,
            "target_impedance_ohm": 50.0,
            "max_volume_mm3": 8000.0,
            "wearable": True,
        }
        result = agent.evaluate_topologies(reqs)
        self.assertIn("candidates", result)
        self.assertIn("recommended", result)
        self.assertIn(result["recommended"]["topology"], ["pifa", "ifa", "meander", "patch", "monopole", "dipole"])
        self.assertIn("closed_form_dimensions", result["recommended"])

    def test_wearable_evaluator(self):
        evaluator = WearableAntennaEvaluator()
        sar = evaluator.evaluate_sar(input_power_w=0.1, antenna_distance_skin_mm=5.0, frequency_hz=2.45e9)
        self.assertIn("sar_1g_w_kg", sar)
        self.assertEqual(sar["regulatory_status"], "NOT_A_COMPLIANCE_DETERMINATION")
        self.assertNotIn("fcc_compliant", sar)

    def test_chief_orchestrator(self):
        orchestrator = ChiefOrchestrator()
        res = orchestrator.run_pipeline("SmartGlasses", {"center_frequency_hz": 2.45e9})
        self.assertEqual(res["status"], "completed")
        self.assertEqual(res["cost_report"]["total_cost_usd"], 0.0)


if __name__ == "__main__":
    unittest.main()
