"""Tests for Prompt2CST optimization subsystem: schema, sensitivity, algorithms, staged optimizer, supervisor, cache, runner, history, pipeline."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from prompt2cst.optimizer.algorithms import DifferentialEvolutionOptimizer, ParameterSweepOptimizer
from prompt2cst.optimizer.cache import SimulationResultCache
from prompt2cst.optimizer.history import OptimizationHistoryLogger
from prompt2cst.optimizer.parameter_meta import infer_parameter_roles
from prompt2cst.optimizer.pipeline import OptimizationPipeline, OptimizationPipelineConfig
from prompt2cst.optimizer.runner import MockCSTRunner
from prompt2cst.optimizer.schema import OptimizationGoalConfig, ParameterBound, compute_impedance_error, s11_from_impedance
from prompt2cst.optimizer.sensitivity import FiniteDifferenceSensitivity
from prompt2cst.optimizer.staged_optimizer import StagedOptimizer
from prompt2cst.optimizer.supervisor import OptimizationSupervisor


class TestOptimizer(unittest.TestCase):
    def test_impedance_error_computation(self):
        err = compute_impedance_error(zin_re=50.0, zin_im=0.0, target_re=50.0, target_im=0.0)
        self.assertEqual(err, 0.0)

        err_off = compute_impedance_error(zin_re=40.0, zin_im=10.0, target_re=50.0, target_im=0.0)
        self.assertGreater(err_off, 0.0)

    def test_s11_from_impedance_returns_real_value(self):
        self.assertEqual(s11_from_impedance(50.0, 0.0), -float("inf"))
        self.assertAlmostEqual(s11_from_impedance(75.0, 0.0), -13.9794, places=3)

    def test_parameter_roles(self):
        roles = infer_parameter_roles("pifa", ["patch_length_mm", "feed_offset_mm", "short_pin_width_mm"])
        self.assertEqual(roles["patch_length_mm"], "resonance")
        self.assertEqual(roles["feed_offset_mm"], "resistance_matching")

    def test_mock_cst_runner(self):
        runner = MockCSTRunner()
        res = runner.run_simulation({"patch_length_mm": 30.0, "patch_width_mm": 20.0})
        self.assertIsNotNone(res.get_value("s11_db"))
        self.assertIsNotNone(res.get_impedance())

    def test_mock_runner_is_reproducible_and_cache_context_isolated(self):
        params = {"patch_length_mm": 30.0, "patch_width_mm": 20.0}
        self.assertEqual(MockCSTRunner().run(params), MockCSTRunner().run(params))
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = SimulationResultCache(Path(tmpdir) / "cache.db")
            cache.put(params, {"s11": -12.0}, context="MOCK_SIMULATION")
            self.assertIsNone(cache.get(params, context="CST_SIMULATION|project.cst"))
            self.assertEqual(cache.get(params, context="MOCK_SIMULATION"), {"s11": -12.0})
            cache.close()

    def test_sensitivity_analysis(self):
        runner = MockCSTRunner()
        bounds = [
            ParameterBound("length_mm", 20.0, 40.0, 30.0),
            ParameterBound("width_mm", 10.0, 30.0, 20.0),
        ]
        sens = FiniteDifferenceSensitivity(runner, bounds)
        report = sens.analyze()
        self.assertIn("ranking", report)
        self.assertEqual(len(report["ranking"]), 2)

    def test_de_optimizer(self):
        runner = MockCSTRunner()
        goal = OptimizationGoalConfig()
        bounds = [
            ParameterBound("length_mm", 25.0, 35.0, 30.0),
            ParameterBound("width_mm", 15.0, 25.0, 20.0),
        ]
        optimizer = DifferentialEvolutionOptimizer(bounds, goal, runner, max_iterations=5)
        res = optimizer.optimize()
        self.assertIsNotNone(res.best_params)
        self.assertIsNotNone(res.best_cost)

    def test_de_fallback_respects_exact_candidate_budget(self):
        optimizer = DifferentialEvolutionOptimizer(
            population_size=10, seed=42, max_total_evaluations=7
        )
        with patch.dict(sys.modules, {"scipy": None, "scipy.optimize": None}):
            result = optimizer.optimize(
                cost_fn=lambda params: params["length_mm"] ** 2,
                param_bounds={"length_mm": (1.0, 5.0)},
                max_iterations=5,
            )
        self.assertEqual(result.evaluations, 7)
        self.assertEqual(len(result.history), 7)

    def test_de_scipy_respects_exact_candidate_budget(self):
        try:
            import scipy.optimize  # noqa: F401
        except ImportError:
            self.skipTest("SciPy is not installed")
        optimizer = DifferentialEvolutionOptimizer(
            population_size=10, seed=42, max_total_evaluations=25
        )
        result = optimizer.optimize(
            cost_fn=lambda params: params["length_mm"] ** 2 + params["width_mm"] ** 2,
            param_bounds={"length_mm": (1.0, 5.0), "width_mm": (1.0, 5.0)},
            max_iterations=5,
        )
        self.assertEqual(result.evaluations, 25)
        self.assertFalse(result.converged)

    def test_staged_optimizer(self):
        runner = MockCSTRunner()
        goal = OptimizationGoalConfig()
        bounds = [
            ParameterBound("length_mm", 25.0, 35.0, 30.0),
            ParameterBound("feed_offset_mm", 2.0, 8.0, 5.0),
        ]
        staged = StagedOptimizer("pifa", bounds, goal, runner, max_iterations_per_stage=3)
        res = staged.optimize()
        self.assertTrue(res["completed"])
        self.assertEqual(len(res["stages"]), 4)

    def test_optimization_supervisor(self):
        sup = OptimizationSupervisor()
        sim_res = MockCSTRunner().run_simulation({"length_mm": 30.0})
        goal = OptimizationGoalConfig()
        diagnosis = sup.diagnose(sim_res, goal)
        self.assertIn("failure_modes", diagnosis)
        self.assertIn("suggestions", diagnosis)

    def test_cache_and_history(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = SimulationResultCache(Path(tmpdir) / "cache.db")
            params = {"length": 30.0, "width": 20.0}
            self.assertIsNone(cache.get(params))
            cache.put(params, {"s11": -12.0})
            cached = cache.get(params)
            self.assertEqual(cached, {"s11": -12.0})
            cache.close()

            history = OptimizationHistoryLogger(Path(tmpdir) / "hist.json")
            history.log_iteration(1, "stage_a", params, {"s11": -12.0}, 0.05)
            self.assertEqual(len(history.records), 1)

    def test_optimization_pipeline(self):
        goal = OptimizationGoalConfig()
        bounds = [
            ParameterBound("length_mm", 25.0, 35.0, 30.0),
            ParameterBound("width_mm", 15.0, 25.0, 20.0),
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = OptimizationPipelineConfig(
                project_name="TestPipeline",
                topology_name="pifa",
                goal=goal,
                bounds=bounds,
                output_dir=Path(tmpdir),
                max_iterations=5,
            )
            pipeline = OptimizationPipeline(cfg, runner=MockCSTRunner())
            try:
                res = pipeline.run()
            finally:
                pipeline.cache.close()
        self.assertEqual(res["status"], "completed")
        self.assertIn("best_parameters", res)
        # The configured budget is per stage. DE evaluates a population, so
        # candidate evaluations can exceed five while remaining bounded.
        self.assertLessEqual(res["optimization"]["total_evaluations"], 12 * cfg.max_iterations)

    def test_pipeline_budget_without_scipy(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = OptimizationPipelineConfig(
                project_name="NoSciPyBudget",
                topology_name="pifa",
                goal=OptimizationGoalConfig(),
                bounds=[
                    ParameterBound("length_mm", 25.0, 35.0, 30.0),
                    ParameterBound("width_mm", 15.0, 25.0, 20.0),
                ],
                output_dir=Path(tmpdir),
                max_iterations=5,
            )
            pipeline = OptimizationPipeline(cfg, runner=MockCSTRunner())
            try:
                with patch.dict(sys.modules, {"scipy": None, "scipy.optimize": None}):
                    result = pipeline.run()
            finally:
                pipeline.cache.close()
        self.assertLessEqual(result["optimization"]["total_evaluations"], 60)


if __name__ == "__main__":
    unittest.main()
