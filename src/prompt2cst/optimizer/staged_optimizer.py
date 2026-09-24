"""Staged optimization manager.

Stages:
  A - Resonance tuning (adjust parameters affecting resonant frequency)
  B - Resistance/impedance matching (Re(Zin) → Z0)
  C - S11/bandwidth optimization (overall S11 and bandwidth)
  D - Performance optimization (gain, efficiency, etc.)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Callable

from .algorithms import (
    DifferentialEvolutionOptimizer,
    OptimizationResult,
    Optimizer,
    ParameterSweepOptimizer,
)
from .parameter_meta import ParameterMeta, ParameterRole, prioritize_parameters
from .schema import OptimizationGoalSchema

logger = logging.getLogger(__name__)


class OptimizationStage(StrEnum):
    RESONANCE = "A_resonance"
    IMPEDANCE = "B_impedance"
    S11_BANDWIDTH = "C_s11_bandwidth"
    PERFORMANCE = "D_performance"


# Which parameter roles are relevant to each stage
_STAGE_ROLES: dict[OptimizationStage, list[ParameterRole]] = {
    OptimizationStage.RESONANCE: [ParameterRole.RESONANCE],
    OptimizationStage.IMPEDANCE: [
        ParameterRole.RESISTANCE_MATCHING,
        ParameterRole.REACTANCE_MATCHING,
    ],
    OptimizationStage.S11_BANDWIDTH: [
        ParameterRole.RESONANCE,
        ParameterRole.RESISTANCE_MATCHING,
        ParameterRole.REACTANCE_MATCHING,
        ParameterRole.BANDWIDTH,
    ],
    OptimizationStage.PERFORMANCE: [
        ParameterRole.GAIN,
        ParameterRole.EFFICIENCY,
        ParameterRole.COUPLING,
        ParameterRole.BANDWIDTH,
    ],
}


@dataclass(frozen=True)
class StageResult:
    """Result of a single optimization stage."""

    stage: OptimizationStage
    result: OptimizationResult
    active_parameters: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "result": self.result.to_dict(),
            "active_parameters": self.active_parameters,
        }


@dataclass
class StagedOptimizer:
    """Orchestrates multi-stage optimization."""

    topology: str = "patch"
    bounds: list[Any] = field(default_factory=list)
    goal: OptimizationGoalSchema = field(default_factory=OptimizationGoalSchema)
    runner: Any = None
    max_iterations_per_stage: int = 10
    parameter_metas: list[ParameterMeta] = field(default_factory=list)
    param_bounds: dict[str, tuple[float, float]] = field(default_factory=dict)
    stage_results: list[StageResult] = field(default_factory=list)

    def __post_init__(self) -> None:
        if isinstance(self.topology, OptimizationGoalSchema):
            # Positional fallback if called as (goal, metas, bounds)
            g = self.topology
            metas = self.bounds if isinstance(self.bounds, list) else []
            pbounds = self.goal if isinstance(self.goal, dict) else {}
            self.goal = g
            self.parameter_metas = metas
            self.param_bounds = pbounds
            self.topology = "patch"
        elif self.bounds and isinstance(self.bounds, list) and not self.param_bounds:
            self.param_bounds = {
                b.name: (b.min_value, b.max_value)
                for b in self.bounds
                if hasattr(b, "name")
            }

    def optimize(self) -> dict[str, Any]:
        initial_params = {
            b.name: getattr(b, "default_value", (b.min_value + b.max_value) / 2)
            for b in self.bounds
            if hasattr(b, "name")
        } or {"length_mm": 30.0}

        def cost_fn(params):
            if self.runner:
                res = self.runner.run_simulation(params)
                s11 = res.get_s11_db() if hasattr(res, "get_s11_db") else -10.0
                return abs((s11 or -10.0) - (-15.0))
            return 0.1

        res = self.run_all_stages(cost_fn, initial_params)
        res["completed"] = True
        res["best_parameters"] = res.get("final_params", initial_params)
        return res

    def run_all_stages(
        self,
        cost_fn: Callable[[dict[str, float]], float],
        initial_params: dict[str, float],
        stages: list[OptimizationStage] | None = None,
        stage_cost_fn: Callable[[OptimizationStage, dict[str, float]], float] | None = None,
        stage_completed: Callable[[OptimizationStage, dict[str, float]], None] | None = None,
    ) -> dict[str, Any]:
        """Run all optimization stages sequentially.

        Each stage starts from the best parameters found in the
        previous stage.
        """
        stages = stages or list(OptimizationStage)
        current_params = dict(initial_params)

        for stage in stages:
            logger.info("Starting optimization stage: %s", stage)
            active_cost = (lambda params, active_stage=stage: stage_cost_fn(active_stage, params)) if stage_cost_fn else cost_fn
            stage_result = self.run_stage(stage, active_cost, current_params)
            self.stage_results.append(stage_result)

            # Update params for next stage
            current_params.update(stage_result.result.best_params)
            if stage_completed:
                stage_completed(stage, current_params)

            logger.info(
                "Stage %s complete: cost=%.4f, converged=%s",
                stage,
                stage_result.result.best_cost,
                stage_result.result.converged,
            )

        return {
            "stages": [sr.to_dict() for sr in self.stage_results],
            "final_params": current_params,
            "total_evaluations": sum(
                sr.result.evaluations for sr in self.stage_results
            ),
        }

    def run_stage(
        self,
        stage: OptimizationStage,
        cost_fn: Callable[[dict[str, float]], float],
        current_params: dict[str, float],
    ) -> StageResult:
        """Run a single optimization stage."""
        # Get parameters relevant to this stage
        roles = _STAGE_ROLES[stage]
        active_metas = prioritize_parameters(self.parameter_metas, roles)

        if not active_metas:
            # If no role-specific params, use all params
            active_metas = list(self.parameter_metas)

        active_names = [m.name for m in active_metas if m.name in self.param_bounds]

        if not active_names:
            logger.warning("No active parameters for stage %s", stage)
            return StageResult(
                stage=stage,
                result=OptimizationResult(
                    best_params=current_params,
                    best_cost=float("inf"),
                    iterations=0,
                    evaluations=0,
                    converged=False,
                    history=[],
                ),
                active_parameters=[],
            )

        # Build bounds for active parameters only
        active_bounds = {n: self.param_bounds[n] for n in active_names}

        # Select optimizer: sweep for coarse stages, DE for fine
        if stage in (OptimizationStage.RESONANCE, OptimizationStage.IMPEDANCE):
            optimizer: Optimizer = ParameterSweepOptimizer(
                points_per_param=7,
                max_total_evaluations=self.max_iterations_per_stage,
            )
            max_iter = self.max_iterations_per_stage
        else:
            optimizer = DifferentialEvolutionOptimizer(
                population_size=10,
                seed=42,
                max_total_evaluations=self.max_iterations_per_stage * 5,
            )
            max_iter = min(self.goal.max_iterations, self.max_iterations_per_stage)

        # Create a cost function that fixes non-active params
        def stage_cost(active_params: dict[str, float]) -> float:
            full_params = dict(current_params)
            full_params.update(active_params)
            return cost_fn(full_params)

        result = optimizer.optimize(
            cost_fn=stage_cost,
            param_bounds=active_bounds,
            initial_params={n: current_params.get(n, 0) for n in active_names},
            max_iterations=max_iter,
            convergence_threshold=self.goal.convergence_threshold,
        )

        return StageResult(
            stage=stage,
            result=result,
            active_parameters=active_names,
        )
