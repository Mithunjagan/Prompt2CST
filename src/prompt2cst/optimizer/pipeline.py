"""Pipeline orchestrator for the optimization subsystem.

Coordinates pre-simulation geometry validation, sensitivity analysis,
staged optimization, caching, history logging, early stopping,
and report generation.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .algorithms import OptimizationResult
from .cache import ResultCache
from .checkpoint import CheckpointData, CheckpointManager
from .history import IterationHistory
from .parameter_meta import ParameterMeta, ParameterRole, build_parameter_metadata
from .runner import CSTRunnerBase, DryRunRunner, MockCSTRunner
from .schema import OptimizationGoalSchema, impedance_error, s11_from_impedance
from .sensitivity import SensitivityAnalyzer
from .staged_optimizer import StagedOptimizer
from .supervisor import OptimizationSupervisor, classify_failure

logger = logging.getLogger(__name__)


@dataclass
class OptimizationPipelineConfig:
    project_name: str
    topology_name: str
    goal: Any
    bounds: list[Any]
    output_dir: Path = field(default_factory=lambda: Path("outputs"))
    max_iterations: int = 15
    execution_mode: str = "mock"
    resume: bool = False


class OptimizationPipeline:
    """End-to-end optimization pipeline."""

    def __init__(
        self,
        runner_or_config: Any,
        goal: Any = None,
        output_dir: Path | str | None = None,
        topology: str = "patch",
        runner: Any = None,
    ) -> None:
        if isinstance(runner_or_config, OptimizationPipelineConfig):
            cfg = runner_or_config
            self.config = cfg
            self.runner = runner or MockCSTRunner()
            self.topology = cfg.topology_name
            self.output_dir = Path(cfg.output_dir)
            self.goal = cfg.goal
            self.bounds = cfg.bounds
            self.execution_mode = cfg.execution_mode
            self.max_iterations_per_stage = cfg.max_iterations
        else:
            self.config = None
            self.runner = runner_or_config
            self.goal = goal or OptimizationGoalSchema()
            self.output_dir = Path(output_dir or "outputs")
            self.topology = topology
            self.bounds = []
            self.execution_mode = "cst" if self.runner.label() == "CST_SIMULATION" else "mock"
            self.max_iterations_per_stage = self.goal.max_iterations

        if self.execution_mode not in {"mock", "cst"}:
            raise ValueError("execution_mode must be 'mock' or 'cst'")
        if self.execution_mode == "cst" and self.runner.label() != "CST_SIMULATION":
            raise ValueError("--mode cst requires a CST_SIMULATION runner; mock physics is rejected.")

        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.cache = ResultCache(self.output_dir / "cache.db")
        self.history = IterationHistory(self.output_dir)
        self.checkpoints = CheckpointManager(self.output_dir)
        self._checkpoint = self.checkpoints.load() if self.config and self.config.resume else None
        self._current_stage = "initial"
        self.supervisor = OptimizationSupervisor()
        self._eval_count = 0

    def _save_checkpoint(
        self,
        parameters: dict[str, float],
        result: dict[str, float],
        *,
        status: str = "in_progress",
        completed_stages: list[str] | None = None,
    ) -> None:
        """Atomically persist enough state to continue after an interruption.

        The result cache prevents an already completed real CST candidate from
        being run again after a resumed process.
        """
        existing = self._checkpoint or CheckpointData(
            project_name=getattr(self.config, "project_name", self.output_dir.name) if self.config else self.output_dir.name,
            topology_name=self.topology,
        )
        previous_best = existing.best_cost
        candidate_cost = self._cost_from_result(result)
        is_best = candidate_cost < previous_best
        self._checkpoint = CheckpointData(
            project_name=existing.project_name,
            topology_name=self.topology,
            status=status,
            current_iteration=self._eval_count,
            completed_stages=completed_stages if completed_stages is not None else existing.completed_stages,
            current_stage=self._current_stage,
            latest_parameters=dict(parameters),
            latest_simulation_result=dict(result),
            best_cost=candidate_cost if is_best else previous_best,
            best_parameters=dict(parameters) if is_best else existing.best_parameters,
            best_result=dict(result) if is_best else existing.best_result,
            history_records=[record.to_dict() for record in self.history.records],
        )
        self.checkpoints.save(self._checkpoint)

    def _cost_from_result(self, result: dict[str, float]) -> float:
        return self._cost_for_stage("A_resonance", result)

    # ------------------------------------------------------------------
    # Geometry validation
    # ------------------------------------------------------------------

    def validate_geometry(
        self,
        parameters: dict[str, float],
    ) -> dict[str, Any]:
        """Pre-simulation geometry validation.

        Checks for physically impossible dimensions (negative lengths,
        overlapping structures, etc.)
        """
        errors: list[str] = []
        warnings: list[str] = []

        for name, value in parameters.items():
            # Check for negative dimensions
            if any(k in name.lower() for k in ("length", "width", "height", "radius", "thick")):
                if value <= 0:
                    errors.append(f"{name} = {value} (must be positive)")
                elif value < 0.01:
                    warnings.append(f"{name} = {value} mm (very small, may cause mesh issues)")
                elif value > 1000:
                    warnings.append(f"{name} = {value} mm (very large)")

        return {
            "valid": len(errors) == 0,
            "errors": errors,
            "warnings": warnings,
        }

    # ------------------------------------------------------------------
    # Cached simulation
    # ------------------------------------------------------------------

    def _simulate(self, parameters: dict[str, float]) -> dict[str, float]:
        """Run simulation with caching."""
        assert self.cache is not None
        cache_context = json.dumps({
            "runner": self.runner.cache_identity(), "topology": self.topology,
            "frequency_min_ghz": self.goal.frequency_range.min_ghz,
            "frequency_max_ghz": self.goal.frequency_range.max_ghz,
        }, sort_keys=True)

        cached = self.cache.get(parameters, context=cache_context)
        if cached is not None:
            return cached

        result = self.runner.run(
            parameters,
            self.goal.frequency_range.min_ghz,
            self.goal.frequency_range.max_ghz,
        )
        self.cache.put(parameters, result, self.runner.label(), context=cache_context)
        self._eval_count += 1
        self._save_checkpoint(parameters, result)
        return result

    # ------------------------------------------------------------------
    # Cost function
    # ------------------------------------------------------------------

    def _cost_function(self, parameters: dict[str, float]) -> float:
        """Multi-objective cost function for optimization."""
        result = self._simulate(parameters)
        cost = 0.0
        z0 = self.goal.reference_impedance_ohm

        for obj in self.goal.objectives:
            metric_val = 0.0

            if obj.metric == "s11_db":
                s11 = result.get("s11_db")
                if s11 is None:
                    z_real = result.get("z_real", 50.0)
                    z_imag = result.get("z_imag", 0.0)
                    s11 = s11_from_impedance(z_real, z_imag, z0)
                s11_val = s11 if s11 is not None else -10.0
                target = obj.target if obj.target is not None else -10.0
                metric_val = max(0, s11_val - target)

            elif obj.metric == "impedance_error":
                z_real = result.get("z_real", 50.0)
                z_imag = result.get("z_imag", 0.0)
                metric_val = impedance_error(z_real, z_imag, z0)

            elif obj.metric == "normalized_impedance_error":
                z_real = result.get("z_real", 50.0)
                z_imag = result.get("z_imag", 0.0)
                metric_val = impedance_error(z_real, z_imag, z0) / z0

            elif obj.metric == "resonance_offset_mhz":
                f_res = result.get("f_res_ghz", 0)
                target_f = self.goal.frequency_range.center_ghz
                metric_val = abs(f_res - target_f) * 1000  # in MHz

            elif obj.metric == "bandwidth_mhz":
                bw = result.get("bandwidth_mhz", 0)
                target_bw = obj.target or 100
                metric_val = max(0, target_bw - bw)

            elif obj.metric == "gain_dbi":
                gain = result.get("gain_dbi", 0)
                target_gain = obj.target or 0
                metric_val = max(0, target_gain - gain)

            elif obj.metric == "efficiency":
                eff = result.get("efficiency_pct", 0)
                target_eff = obj.target or 50
                metric_val = max(0, target_eff - eff)

            cost += obj.weight * metric_val

        return cost

    def _cost_for_stage(self, stage: str, result: dict[str, float]) -> float:
        """Use RF metrics appropriate to the current staged objective."""
        z0 = self.goal.reference_impedance_ohm
        if stage == "A_resonance":
            return abs(float(result["f_res_ghz"]) - self.goal.frequency_range.center_ghz) * 1000.0
        if stage == "B_impedance":
            return impedance_error(float(result["z_real"]), float(result["z_imag"]), z0)
        if stage == "C_s11_bandwidth":
            s11 = float(result["s11_db"])
            target = self.goal.early_stop_s11_db
            bandwidth_penalty = max(0.0, 100.0 - float(result.get("bandwidth_mhz", 0.0))) / 100.0
            return max(0.0, s11 - target) + bandwidth_penalty
        return self._cost_function_from_result(result)

    def _cost_function_from_result(self, result: dict[str, float]) -> float:
        """Evaluate configured objectives against an already-extracted result."""
        z0 = self.goal.reference_impedance_ohm
        cost = 0.0
        for obj in self.goal.objectives:
            if obj.metric == "s11_db":
                metric = max(0.0, float(result["s11_db"]) - (obj.target if obj.target is not None else -10.0))
            elif obj.metric == "impedance_error":
                metric = impedance_error(float(result["z_real"]), float(result["z_imag"]), z0)
            elif obj.metric == "normalized_impedance_error":
                metric = impedance_error(float(result["z_real"]), float(result["z_imag"]), z0) / z0
            elif obj.metric == "resonance_offset_mhz":
                metric = abs(float(result["f_res_ghz"]) - self.goal.frequency_range.center_ghz) * 1000.0
            elif obj.metric == "bandwidth_mhz":
                metric = max(0.0, (obj.target or 100.0) - float(result.get("bandwidth_mhz", 0.0)))
            else:
                metric = 0.0
            cost += obj.weight * metric
        return cost

    # ------------------------------------------------------------------
    # Full pipeline
    # ------------------------------------------------------------------

    def run(
        self,
        initial_params: dict[str, float] | None = None,
        param_bounds: dict[str, tuple[float, float]] | None = None,
    ) -> dict[str, Any]:
        start_time = time.time()

        if self._checkpoint and self._checkpoint.status != "completed" and self._checkpoint.latest_parameters:
            initial_params = dict(self._checkpoint.latest_parameters)
        if initial_params is None:
            initial_params = {}
            if hasattr(self, "bounds") and self.bounds:
                for b in self.bounds:
                    if hasattr(b, "name"):
                        def_val = getattr(b, "default_value", (b.min_value + b.max_value) / 2)
                        initial_params[b.name] = def_val
                        if param_bounds is None:
                            param_bounds = param_bounds or {}
                            param_bounds[b.name] = (b.min_value, b.max_value)
            if not initial_params:
                initial_params = {"patch_length_mm": 30.0, "patch_width_mm": 20.0}
        assert self.history is not None
        assert self.supervisor is not None

        # 1. Validate geometry
        validation = self.validate_geometry(initial_params)
        if not validation["valid"]:
            return {
                "status": "failed",
                "stage": "geometry_validation",
                "errors": validation["errors"],
            }

        # 2. Auto-generate bounds if needed
        if param_bounds is None:
            param_bounds = {}
            for name, value in initial_params.items():
                if value > 0:
                    param_bounds[name] = (value * 0.7, value * 1.3)
                else:
                    param_bounds[name] = (value - 1.0, value + 1.0)

        # 3. Initial simulation
        logger.info("Running initial simulation...")
        initial_result = self._simulate(initial_params)
        initial_cost = self._cost_function(initial_params)
        self.history.log(0, initial_params, initial_result, initial_cost, "initial")

        # 4. Initial diagnosis
        diagnoses = self.supervisor.diagnose(initial_result)
        logger.info(
            "Initial S11: %.1f dB, Z = %.1f%+.1fj Ω, %d issues found",
            initial_result.get("s11_db", 0),
            initial_result.get("z_real", 0),
            initial_result.get("z_imag", 0),
            len(diagnoses),
        )

        # 5. Sensitivity analysis
        logger.info("Running sensitivity analysis...")
        sensitivity_analyzer = SensitivityAnalyzer(
            sim_fn=self._simulate,
            metrics=["f_res_ghz", "z_real", "z_imag", "s11_db"],
        )
        sensitivity_results = sensitivity_analyzer.analyze(initial_params)
        sensitivity_report = sensitivity_analyzer.sensitivity_report(sensitivity_results)

        # Save sensitivity report
        sens_path = self.output_dir / "sensitivity_report.json"
        sens_path.write_text(
            json.dumps(sensitivity_report, indent=2, default=str),
            encoding="utf-8",
        )

        # 6. Build parameter metadata
        param_info = {
            name: {"min": bounds[0], "max": bounds[1]}
            for name, bounds in param_bounds.items()
        }
        param_metas = build_parameter_metadata(param_info, self.topology)

        # Update sensitivity ranks
        s11_ranking = sensitivity_analyzer.rank_parameters(
            sensitivity_results, "s11_db"
        )
        ranked_names = {name: rank for rank, (name, _) in enumerate(s11_ranking, 1)}
        param_metas = [
            ParameterMeta(
                name=m.name,
                role=m.role,
                sensitivity_rank=ranked_names.get(m.name, 0),
                description=m.description,
                min_value=m.min_value,
                max_value=m.max_value,
                step_size=m.step_size,
            )
            for m in param_metas
        ]

        # 7. Staged optimization
        logger.info("Starting staged optimization...")
        staged = StagedOptimizer(
            goal=self.goal,
            parameter_metas=param_metas,
            param_bounds=param_bounds,
            max_iterations_per_stage=max(1, self.max_iterations_per_stage),
        )
        completed = list(self._checkpoint.completed_stages) if self._checkpoint else []
        stages = [stage for stage in __import__("prompt2cst.optimizer.staged_optimizer", fromlist=["OptimizationStage"]).OptimizationStage if str(stage) not in completed]

        def stage_cost(stage: Any, params: dict[str, float]) -> float:
            self._current_stage = str(stage)
            return self._cost_for_stage(str(stage), self._simulate(params))

        def stage_done(stage: Any, params: dict[str, float]) -> None:
            self._current_stage = str(stage)
            result = self._simulate(params)
            done = completed + [str(stage)]
            self._save_checkpoint(params, result, completed_stages=done)

        staged_result = staged.run_all_stages(
            cost_fn=self._cost_function,
            initial_params=initial_params,
            stages=stages,
            stage_cost_fn=stage_cost,
            stage_completed=stage_done,
        )

        # 8. Log final result
        final_params = staged_result["final_params"]
        final_result = self._simulate(final_params)
        final_cost = self._cost_function(final_params)
        self.history.log(
            len(self.history.records),
            final_params,
            final_result,
            final_cost,
            "final",
        )

        # 9. Final diagnosis
        final_diagnoses = self.supervisor.diagnose(final_result)

        # 10. Save history
        self.history.save_json()
        self.history.save_csv()
        self._current_stage = "completed"
        self._save_checkpoint(final_params, final_result, status="completed", completed_stages=[str(stage) for stage in __import__("prompt2cst.optimizer.staged_optimizer", fromlist=["OptimizationStage"]).OptimizationStage])

        elapsed = time.time() - start_time

        return {
            "status": "completed",
            "elapsed_seconds": round(elapsed, 2),
            "best_parameters": final_params,
            "initial": {
                "params": initial_params,
                "result": initial_result,
                "cost": round(initial_cost, 4),
                "diagnoses": [d.to_dict() for d in diagnoses],
            },
            "sensitivity": sensitivity_report,
            "optimization": staged_result,
            "final": {
                "params": {k: round(v, 4) for k, v in final_params.items()},
                "result": final_result,
                "cost": round(final_cost, 4),
                "diagnoses": [d.to_dict() for d in final_diagnoses],
            },
            "cache_stats": self.cache.stats() if self.cache else {},
            "total_simulations": self._eval_count,
            "runner_label": self.runner.label(),
        }
