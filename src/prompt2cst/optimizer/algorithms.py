"""Optimization algorithms: Parameter Sweep and Differential Evolution.

Pure Python / SciPy implementations with no paid API dependencies.
"""

from __future__ import annotations

import itertools
import logging
import math
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class OptimizationResult:
    """Result of an optimization run."""

    best_params: dict[str, float]
    best_cost: float
    iterations: int
    evaluations: int
    converged: bool
    history: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "best_params": {k: round(v, 6) for k, v in self.best_params.items()},
            "best_cost": round(self.best_cost, 6),
            "iterations": self.iterations,
            "evaluations": self.evaluations,
            "converged": self.converged,
            "history_length": len(self.history),
        }


class Optimizer(ABC):
    """Abstract base for optimization algorithms."""

    @abstractmethod
    def optimize(
        self,
        cost_fn: Callable[[dict[str, float]], float],
        param_bounds: dict[str, tuple[float, float]],
        initial_params: dict[str, float] | None = None,
        max_iterations: int = 50,
        convergence_threshold: float = 0.01,
    ) -> OptimizationResult:
        """Run optimization and return results."""
        ...


@dataclass
class ParameterSweepOptimizer(Optimizer):
    """Grid-based parameter sweep optimizer.

    Evaluates the cost function at evenly-spaced points within
    each parameter's bounds.
    """

    points_per_param: int = 5
    max_total_evaluations: int = 500

    def optimize(
        self,
        cost_fn: Callable[[dict[str, float]], float],
        param_bounds: dict[str, tuple[float, float]],
        initial_params: dict[str, float] | None = None,
        max_iterations: int = 50,
        convergence_threshold: float = 0.01,
    ) -> OptimizationResult:
        param_names = list(param_bounds.keys())
        n_params = len(param_names)

        # Compute points per parameter to stay within budget
        if n_params == 0:
            return OptimizationResult(
                best_params=initial_params or {},
                best_cost=float("inf"),
                iterations=0,
                evaluations=0,
                converged=False,
                history=[],
            )

        pts = self.points_per_param
        while pts ** n_params > self.max_total_evaluations and pts > 2:
            pts -= 1

        # Generate grid
        param_values: dict[str, list[float]] = {}
        for name in param_names:
            lo, hi = param_bounds[name]
            if pts <= 1:
                param_values[name] = [(lo + hi) / 2]
            else:
                step = (hi - lo) / (pts - 1)
                param_values[name] = [lo + i * step for i in range(pts)]

        best_cost = float("inf")
        best_params: dict[str, float] = initial_params or {
            k: (v[0] + v[-1]) / 2 for k, v in param_values.items()
        }
        history: list[dict[str, Any]] = []
        evaluations = 0

        # Sweep all combinations
        value_lists = [param_values[n] for n in param_names]
        for combo in itertools.product(*value_lists):
            params = dict(zip(param_names, combo))
            try:
                cost = cost_fn(params)
            except Exception as exc:
                logger.debug("Sweep evaluation failed: %s", exc)
                continue
            evaluations += 1

            entry = {"iteration": evaluations, "params": dict(params), "cost": cost}
            history.append(entry)

            if cost < best_cost:
                best_cost = cost
                best_params = dict(params)

            if evaluations >= self.max_total_evaluations:
                break

        return OptimizationResult(
            best_params=best_params,
            best_cost=best_cost,
            iterations=evaluations,
            evaluations=evaluations,
            converged=False,  # Sweep doesn't converge per se
            history=history,
        )


@dataclass
class DifferentialEvolutionOptimizer(Optimizer):
    """Differential Evolution optimizer using SciPy."""

    bounds: list[Any] = field(default_factory=list)
    goal: Any = None
    runner: Any = None
    max_iterations: int = 50
    population_size: int = 15
    mutation: float = 0.8
    crossover: float = 0.7
    seed: int | None = 42

    def optimize(
        self,
        cost_fn: Callable[[dict[str, float]], float] | None = None,
        param_bounds: dict[str, tuple[float, float]] | None = None,
        initial_params: dict[str, float] | None = None,
        max_iterations: int | None = None,
        convergence_threshold: float = 0.01,
    ) -> Any:
        if max_iterations is None:
            max_iterations = self.max_iterations

        if param_bounds is None and self.bounds:
            param_bounds = {
                b.name: (b.min_value, b.max_value)
                for b in self.bounds
                if hasattr(b, "name")
            }
        param_bounds = param_bounds or {"patch_length_mm": (20.0, 40.0)}

        if cost_fn is None and self.runner is not None:
            def cost_fn(params):
                res = self.runner.run_simulation(params)
                s11 = res.get_s11_db() if hasattr(res, "get_s11_db") else -10.0
                return abs((s11 or -10.0) - (-15.0))
        assert cost_fn is not None
        param_names = list(param_bounds.keys())
        bounds_list = [param_bounds[n] for n in param_names]
        history: list[dict[str, Any]] = []
        eval_count = 0

        def wrapped_cost(x: list[float]) -> float:
            nonlocal eval_count
            params = dict(zip(param_names, x))
            try:
                cost = cost_fn(params)
            except Exception:
                cost = 1e6
            eval_count += 1
            if eval_count % 10 == 0 or eval_count == 1:
                history.append(
                    {"evaluation": eval_count, "params": params, "cost": cost}
                )
            return cost

        try:
            from scipy.optimize import differential_evolution

            result = differential_evolution(
                wrapped_cost,
                bounds=bounds_list,
                maxiter=max_iterations,
                popsize=self.population_size,
                mutation=self.mutation,
                recombination=self.crossover,
                tol=convergence_threshold,
                seed=self.seed,
                disp=False,
            )
            best_params = dict(zip(param_names, result.x))
            return OptimizationResult(
                best_params=best_params,
                best_cost=float(result.fun),
                iterations=result.nit,
                evaluations=result.nfev,
                converged=result.success,
                history=history,
            )

        except ImportError:
            logger.warning(
                "SciPy not available; falling back to random search"
            )
            return self._random_search(
                cost_fn, param_names, bounds_list, max_iterations, history
            )

    def _random_search(
        self,
        cost_fn: Callable[[dict[str, float]], float],
        param_names: list[str],
        bounds_list: list[tuple[float, float]],
        max_iter: int,
        history: list[dict[str, Any]],
    ) -> OptimizationResult:
        import random

        rng = random.Random(self.seed)
        best_cost = float("inf")
        best_params: dict[str, float] = {}
        evaluations = 0

        for i in range(max_iter * self.population_size):
            params = {
                name: rng.uniform(lo, hi)
                for name, (lo, hi) in zip(param_names, bounds_list)
            }
            try:
                cost = cost_fn(params)
            except Exception:
                cost = 1e6
            evaluations += 1
            history.append({"evaluation": evaluations, "params": params, "cost": cost})

            if cost < best_cost:
                best_cost = cost
                best_params = dict(params)

        return OptimizationResult(
            best_params=best_params,
            best_cost=best_cost,
            iterations=max_iter,
            evaluations=evaluations,
            converged=False,
            history=history,
        )
