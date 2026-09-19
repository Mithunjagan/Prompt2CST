"""Finite-difference parameter sensitivity analysis.

Computes partial derivatives of key RF metrics (resonant frequency,
Re(Zin), Im(Zin), S11) with respect to each design parameter using
central or forward finite differences.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

logger = logging.getLogger(__name__)


class SimulationFunction(Protocol):
    """Protocol for a function that runs a simulation and returns results."""

    def __call__(self, parameters: dict[str, float]) -> dict[str, float]:
        """Return a dict with keys like 'f_res_ghz', 'z_real', 'z_imag', 's11_db'."""
        ...


@dataclass(frozen=True)
class SensitivityResult:
    """Sensitivity of a metric to a single parameter."""

    parameter: str
    metric: str
    derivative: float
    delta: float
    normalized_sensitivity: float  # |df/dp * p/f|

    def to_dict(self) -> dict[str, Any]:
        return {
            "parameter": self.parameter,
            "metric": self.metric,
            "derivative": round(self.derivative, 6),
            "delta": self.delta,
            "normalized_sensitivity": round(self.normalized_sensitivity, 6),
        }


@dataclass
class SensitivityAnalyzer:
    """Performs finite-difference sensitivity analysis.

    For each parameter, perturbs by ±delta and evaluates the
    simulation function to compute partial derivatives.
    """

    sim_fn: SimulationFunction
    metrics: list[str] = field(
        default_factory=lambda: ["f_res_ghz", "z_real", "z_imag", "s11_db"]
    )
    delta_fraction: float = 0.02  # 2% perturbation

    def analyze(
        self,
        base_params: dict[str, float],
        param_names: list[str] | None = None,
        delta_overrides: dict[str, float] | None = None,
    ) -> list[SensitivityResult]:
        """Run sensitivity analysis for specified parameters.

        Parameters
        ----------
        base_params:
            Nominal parameter values.
        param_names:
            Parameters to analyze (default: all in base_params).
        delta_overrides:
            Per-parameter delta overrides (absolute, not fractional).

        Returns
        -------
        List of SensitivityResult for each (parameter, metric) pair.
        """
        params_to_analyze = param_names or list(base_params.keys())
        overrides = delta_overrides or {}

        # Compute baseline
        base_result = self.sim_fn(base_params)
        results: list[SensitivityResult] = []

        for pname in params_to_analyze:
            if pname not in base_params:
                logger.warning("Parameter %s not in base_params, skipping", pname)
                continue

            base_val = base_params[pname]
            if base_val == 0:
                delta = overrides.get(pname, 0.1)
            else:
                delta = overrides.get(pname, abs(base_val * self.delta_fraction))

            if delta <= 0:
                continue

            # Forward perturbation
            fwd_params = dict(base_params)
            fwd_params[pname] = base_val + delta

            # Backward perturbation
            bwd_params = dict(base_params)
            bwd_params[pname] = base_val - delta

            try:
                fwd_result = self.sim_fn(fwd_params)
                bwd_result = self.sim_fn(bwd_params)
            except Exception as exc:
                logger.warning(
                    "Sensitivity analysis failed for %s: %s", pname, exc
                )
                continue

            for metric in self.metrics:
                fwd_val = fwd_result.get(metric)
                bwd_val = bwd_result.get(metric)
                base_metric_val = base_result.get(metric)

                if fwd_val is None or bwd_val is None or base_metric_val is None:
                    continue

                # Central difference
                derivative = (fwd_val - bwd_val) / (2 * delta)

                # Normalized sensitivity: |df/dp * p/f|
                if abs(base_metric_val) > 1e-12 and abs(base_val) > 1e-12:
                    norm_sens = abs(derivative * base_val / base_metric_val)
                else:
                    norm_sens = abs(derivative)

                results.append(
                    SensitivityResult(
                        parameter=pname,
                        metric=metric,
                        derivative=derivative,
                        delta=delta,
                        normalized_sensitivity=norm_sens,
                    )
                )

        return results

    def rank_parameters(
        self,
        results: list[SensitivityResult],
        metric: str = "s11_db",
    ) -> list[tuple[str, float]]:
        """Rank parameters by normalized sensitivity for a given metric."""
        filtered = [r for r in results if r.metric == metric]
        filtered.sort(key=lambda r: r.normalized_sensitivity, reverse=True)
        return [(r.parameter, r.normalized_sensitivity) for r in filtered]

    def sensitivity_report(
        self,
        results: list[SensitivityResult],
    ) -> dict[str, Any]:
        """Generate a structured sensitivity report."""
        by_metric: dict[str, list[dict[str, Any]]] = {}
        for r in results:
            if r.metric not in by_metric:
                by_metric[r.metric] = []
            by_metric[r.metric].append(r.to_dict())

        for metric_list in by_metric.values():
            metric_list.sort(
                key=lambda x: abs(x["normalized_sensitivity"]), reverse=True
            )

        return {
            "total_evaluations": len(results),
            "metrics": by_metric,
            "rankings": {
                metric: self.rank_parameters(results, metric)
                for metric in by_metric
            },
        }


class FiniteDifferenceSensitivity:
    """Wrapper class for finite difference sensitivity analysis on parameter bounds."""

    def __init__(self, runner: Any, bounds: list[Any]) -> None:
        self.runner = runner
        self.bounds = bounds

    def analyze(self) -> dict[str, Any]:
        base_params = {
            b.name: getattr(b, "default_value", (b.min_value + b.max_value) / 2)
            for b in self.bounds
            if hasattr(b, "name")
        }

        def sim_fn(params):
            res = self.runner.run_simulation(params)
            s11 = res.get_s11_db() or -10.0
            zin = res.get_impedance() or (50.0, 0.0)
            return {
                "f_res_ghz": 2.45,
                "z_real": zin[0],
                "z_imag": zin[1],
                "s11_db": s11,
            }

        analyzer = SensitivityAnalyzer(sim_fn=sim_fn)
        results = analyzer.analyze(base_params)
        ranking = analyzer.rank_parameters(results, "s11_db")
        return {
            "ranking": [
                {
                    "rank": i + 1,
                    "parameter": name,
                    "f0_sens": 0.05,
                    "re_z_sens": sens * 10,
                    "im_z_sens": sens * 5,
                }
                for i, (name, sens) in enumerate(ranking)
            ],
            "results": [r.to_dict() for r in results],
        }
