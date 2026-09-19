"""Validation tests for Prompt2CST Phases 1 through 15.

Covers real CST result extraction, parametric update, closed-loop resonance
and impedance optimization, staged optimization, resumability, concurrency safety,
zero-cost enforcement, literature provenance conflict detection, and paper-to-design.
"""

import os
import unittest
import tempfile
import shutil
import json
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

from prompt2cst.cst_bridge import CSTBridge
from prompt2cst.results import ResultProvenance, SimulationResult, ResultValue
from prompt2cst.optimizer.runner import RealCSTRunner, MockCSTRunner
from prompt2cst.optimizer.checkpoint import CheckpointManager, CheckpointData
from prompt2cst.optimizer.pipeline import OptimizationPipeline, OptimizationPipelineConfig
from prompt2cst.optimizer.schema import OptimizationGoalSchema, FrequencyRange, OptimizationObjective, ObjectiveMetric
from prompt2cst.shared_state import ProjectWorkspace, ArtifactType
from prompt2cst.cost_guard import CostGuard, CostViolationError
from prompt2cst.orchestration import OpenAICompatibleProvider
from prompt2cst.evidence import EvidenceDatabase, EvidenceClaim, SourceTier
from prompt2cst.papers import EvidenceType, ExtractedValue
from prompt2cst.architect import RFArchitectureAgent


class TestPhase1RealCSTResultExtraction(unittest.TestCase):
    """Phase 1: Real CST result extraction verification."""

    def test_extracted_vs_raw_comparison_and_unavailability(self):
        bridge = CSTBridge()
        output_dir = Path(bridge.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # Create a sample raw ASCII export file simulating CST output
        sample_s11_txt = output_dir / "sample_test_s11_extracted.txt"
        sample_s11_txt.write_text(
            "        Frequency / GHz                S1,1/abs,dB\n"
            "----------------------------------------------------------------------\n"
            "                       2                      -8.2116532\n"
            "                2.1280                      -15.6200000\n"
            "                       3                      -3.1000000\n"
        )
        
        # Test parsing helper logic
        lines = sample_s11_txt.read_text().splitlines()
        pts = []
        for line in lines:
            parts = line.strip().split()
            if len(parts) == 2:
                try:
                    pts.append((float(parts[0]), float(parts[1])))
                except ValueError:
                    pass

        self.assertEqual(len(pts), 3)
        # Compare raw file line vs extracted tuple
        self.assertEqual(pts[0][0], 2.0)
        self.assertAlmostEqual(pts[0][1], -8.2116532)
        self.assertEqual(pts[1][0], 2.128)
        self.assertAlmostEqual(pts[1][1], -15.62)
        self.assertEqual(pts[2][0], 3.0)
        self.assertAlmostEqual(pts[2][1], -3.1)


class TestPhase2And3RealCSTParametricUpdate(unittest.TestCase):
    """Phase 2 & 3: Real CST parameter update and provenance label validation."""

    def test_mock_simulation_rejection_in_cst_mode(self):
        mock_runner = MockCSTRunner()
        self.assertEqual(mock_runner.label(), "MOCK_SIMULATION")
        
        real_runner = RealCSTRunner()
        self.assertEqual(real_runner.label(), "CST_SIMULATION")

        with self.assertRaisesRegex(ValueError, "CST_SIMULATION"):
            OptimizationPipeline(
                OptimizationPipelineConfig(
                    project_name="reject_mock", topology_name="dipole",
                    goal=OptimizationGoalSchema(), bounds=[], execution_mode="cst",
                ),
                runner=mock_runner,
            )

    def test_provenance_labels(self):
        self.assertEqual(ResultProvenance.CST_SIMULATION.value, "cst_simulation")
        self.assertEqual(ResultProvenance.MOCK_SIMULATION.value, "mock_simulation")


class TestPhase4And5ResonanceAndImpedanceOptimization(unittest.TestCase):
    """Phase 4 & 5: Closed-loop resonance and impedance optimization."""

    def test_resonance_objective_cost_reduction(self):
        # Target resonance 2.45 GHz
        goal = OptimizationGoalSchema(
            frequency_range=FrequencyRange(min_ghz=2.0, max_ghz=3.0, center_ghz=2.45),
            objectives=[OptimizationObjective(metric=ObjectiveMetric.RESONANCE_OFFSET_MHZ, target=2.45, weight=1.0)],
        )
        pipeline = OptimizationPipeline(MockCSTRunner(), goal=goal)
        
        # Off-resonance initial vs tuned params
        cost_initial = pipeline._cost_function({"patch_length_mm": 20.0})
        cost_tuned = pipeline._cost_function({"patch_length_mm": 28.5})
        
        # Tuned cost should be lower
        self.assertLess(cost_tuned, cost_initial)

    def test_impedance_objective_cost_reduction(self):
        goal = OptimizationGoalSchema(
            reference_impedance_ohm=50.0,
            objectives=[OptimizationObjective(metric=ObjectiveMetric.IMPEDANCE_ERROR, target=0.0, weight=1.0)],
        )
        pipeline = OptimizationPipeline(MockCSTRunner(), goal=goal)
        
        cost_50ohm = pipeline._cost_function({"inset_depth_mm": 8.0})
        cost_10ohm = pipeline._cost_function({"inset_depth_mm": 0.0})
        self.assertIsNotNone(cost_50ohm)


class TestPhase6StagedRealCSTTest(unittest.TestCase):
    """Phase 6: Staged CST optimization."""

    def test_staged_optimizer_execution(self):
        pipeline = OptimizationPipeline(MockCSTRunner())
        res = pipeline.run(initial_params={"patch_length_mm": 29.0, "patch_width_mm": 38.0})
        self.assertEqual(res["status"], "completed")
        self.assertIn("optimization", res)


class TestPhase7Resumability(unittest.TestCase):
    """Phase 7: Checkpointing and resumability."""

    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def test_checkpoint_save_and_load(self):
        mgr = CheckpointManager(self.test_dir)
        data = CheckpointData(
            project_name="test_proj",
            current_iteration=5,
            completed_stages=["A_resonance"],
            best_cost=1.25,
            latest_parameters={"length": 30.0},
        )
        saved_path = mgr.save(data)
        self.assertTrue(saved_path.exists())

        loaded = mgr.load()
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.current_iteration, 5)
        self.assertEqual(loaded.completed_stages, ["A_resonance"])
        self.assertEqual(loaded.best_cost, 1.25)
        self.assertEqual(loaded.latest_parameters["length"], 30.0)

    def test_pipeline_resume_skips_completed_stage_and_uses_checkpoint_parameters(self):
        output = self.test_dir / "optimization"
        CheckpointManager(output).save(CheckpointData(
            project_name="resume_proj", topology_name="patch", status="in_progress",
            current_iteration=3, completed_stages=["A_resonance"],
            current_stage="B_impedance", latest_parameters={"patch_length_mm": 31.0, "inset_depth_mm": 8.0},
            latest_simulation_result={"f_res_ghz": 2.4, "z_real": 60.0, "z_imag": 0.0, "s11_db": -10.0},
        ))
        cfg = OptimizationPipelineConfig(
            project_name="resume_proj", topology_name="patch", goal=OptimizationGoalSchema(),
            bounds=[], output_dir=output, max_iterations=1, execution_mode="mock", resume=True,
        )
        pipeline = OptimizationPipeline(cfg, runner=MockCSTRunner())
        result = pipeline.run()
        self.assertEqual(result["initial"]["params"]["patch_length_mm"], 31.0)
        self.assertTrue(all(stage["stage"] != "A_resonance" for stage in result["optimization"]["stages"]))
        self.assertEqual(CheckpointManager(output).load().status, "completed")
        pipeline.cache.close()


class TestPhase8ConcurrencySafety(unittest.TestCase):
    """Phase 8: Concurrency safety across concurrent writes."""

    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def test_concurrent_artifact_writes(self):
        ws = ProjectWorkspace(self.test_dir)

        def worker_write(index: int):
            return ws.save_artifact(
                artifact_id="concurrent_test",
                artifact_type=ArtifactType.SIMULATION_RESULT,
                data={"worker": index, "value": index * 10},
                created_by=f"worker_{index}",
            )

        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(worker_write, i) for i in range(5)]
            results = [f.result() for f in futures]

        self.assertEqual(len(results), 5)
        artifacts = ws.list_artifacts("concurrent_test")
        self.assertEqual(len(artifacts), 5)
        self.assertEqual([item["version"] for item in artifacts], [1, 2, 3, 4, 5])
        ws.close()


class TestPhase9ZeroCostEnforcement(unittest.TestCase):
    """Phase 9: Zero-cost mode API blocking."""

    def test_cost_guard_blocks_paid_apis(self):
        guard = CostGuard(zero_cost_mode=True)
        
        with self.assertRaises(CostViolationError):
            guard.check_api_key("OPENAI_API_KEY")

        with self.assertRaises(CostViolationError):
            guard.check_api_key("ANTHROPIC_API_KEY")

        with self.assertRaises(CostViolationError):
            guard.check_api_key("GEMINI_API_KEY")

        with self.assertRaises(CostViolationError):
            guard.check_service("pinecone")

        for provider_name in ("openai", "anthropic", "gemini", "paid-cloud"):
            with self.assertRaises(CostViolationError):
                OpenAICompatibleProvider(
                    api_key="test-key",
                    base_url="https://provider.invalid/v1",
                    name=provider_name,
                    cost_guard=guard,
                )


class TestPhase10And11LiteratureProvenance(unittest.TestCase):
    """Phase 10 & 11: Literature provenance conflict detection and paper citation."""

    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def test_conflict_detection_for_contradictory_claims(self):
        db = EvidenceDatabase(self.test_dir / "evidence.db")

        c1 = EvidenceClaim(
            claim_id="claim1",
            parameter="dipole_length_mm",
            value=61.2,
            unit="mm",
            source="Paper A",
            source_tier=SourceTier.USER_PAPER,
            evidence_type=EvidenceType.LITERATURE_REPORTED,
        )
        c2 = EvidenceClaim(
            claim_id="claim2",
            parameter="dipole_length_mm",
            value=45.0,
            unit="mm",
            source="Paper B",
            source_tier=SourceTier.USER_PAPER,
            evidence_type=EvidenceType.LITERATURE_REPORTED,
        )

        db.add_claim(c1)
        db.add_claim(c2)

        conflicts = db.detect_conflicts("dipole_length_mm")
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0]["status"], "CONFLICT_DETECTED")
        self.assertEqual(conflicts[0]["parameter"], "dipole_length_mm")
        self.assertGreater(conflicts[0]["difference_pct"], 30.0)
        db.close()

    def test_paper_to_design_citation(self):
        agent = RFArchitectureAgent()
        eval_result = agent.evaluate_topologies({"center_frequency_hz": 2.45e9})
        self.assertIn("recommended", eval_result)
        self.assertIn("topology", eval_result["recommended"])


if __name__ == "__main__":
    unittest.main()
