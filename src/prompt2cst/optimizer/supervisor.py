"""LLM optimization supervisor layer.

Provides deterministic failure-mode classification and next-action
suggestions without requiring LLM inference.  When genuine LLM
reasoning is needed, signals ``NEEDS_AGENT``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

logger = logging.getLogger(__name__)


class FailureMode(StrEnum):
    FREQUENCY_MISMATCH = "frequency_mismatch"
    RESISTIVE_MISMATCH = "resistive_mismatch"
    REACTIVE_MISMATCH = "reactive_mismatch"
    BANDWIDTH_PROBLEM = "bandwidth_problem"
    LOW_EFFICIENCY = "low_efficiency"
    LOW_GAIN = "low_gain"
    HIGH_SAR = "high_sar"
    GEOMETRY_INVALID = "geometry_invalid"
    CONVERGENCE_FAILURE = "convergence_failure"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class Diagnosis:
    """Diagnosis of a simulation result."""

    failure_mode: FailureMode
    severity: str  # "minor", "moderate", "severe"
    detail: str
    suggested_actions: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "failure_mode": self.failure_mode,
            "severity": self.severity,
            "detail": self.detail,
            "suggested_actions": self.suggested_actions,
        }


def classify_failure(
    sim_result: dict[str, float],
    target_freq_ghz: float = 2.45,
    target_s11_db: float = -10.0,
    z0: float = 50.0,
) -> list[Diagnosis]:
    """Deterministically classify failure modes from simulation results.

    Parameters
    ----------
    sim_result:
        Dict with keys like 'f_res_ghz', 'z_real', 'z_imag', 's11_db',
        'bandwidth_mhz', 'efficiency_pct', 'gain_dbi'.
    target_freq_ghz:
        Target resonant frequency.
    target_s11_db:
        Target S11 threshold.
    z0:
        Reference impedance.
    """
    diagnoses: list[Diagnosis] = []

    f_res = sim_result.get("f_res_ghz")
    z_real = sim_result.get("z_real")
    z_imag = sim_result.get("z_imag")
    s11 = sim_result.get("s11_db")
    bw = sim_result.get("bandwidth_mhz")
    eff = sim_result.get("efficiency_pct")
    gain = sim_result.get("gain_dbi")

    # 1. Frequency mismatch
    if f_res is not None:
        freq_error_pct = abs(f_res - target_freq_ghz) / target_freq_ghz * 100
        if freq_error_pct > 5:
            severity = "severe" if freq_error_pct > 15 else "moderate"
            direction = "high" if f_res > target_freq_ghz else "low"
            action = (
                "Increase resonant length"
                if direction == "high"
                else "Decrease resonant length"
            )
            diagnoses.append(
                Diagnosis(
                    failure_mode=FailureMode.FREQUENCY_MISMATCH,
                    severity=severity,
                    detail=(
                        f"Resonance at {f_res:.3f} GHz, "
                        f"target {target_freq_ghz:.3f} GHz "
                        f"({freq_error_pct:.1f}% {direction})"
                    ),
                    suggested_actions=[
                        action,
                        "Adjust parameters with RESONANCE role",
                    ],
                )
            )

    # 2. Resistive mismatch
    if z_real is not None:
        r_error = abs(z_real - z0)
        if r_error > 20:
            severity = "severe" if r_error > 50 else "moderate"
            direction = "high" if z_real > z0 else "low"
            diagnoses.append(
                Diagnosis(
                    failure_mode=FailureMode.RESISTIVE_MISMATCH,
                    severity=severity,
                    detail=(
                        f"Re(Zin) = {z_real:.1f} Ω, target {z0:.0f} Ω "
                        f"(error: {r_error:.1f} Ω)"
                    ),
                    suggested_actions=[
                        f"Adjust feed position to {'decrease' if direction == 'high' else 'increase'} input resistance",
                        "Modify parameters with RESISTANCE_MATCHING role",
                    ],
                )
            )

    # 3. Reactive mismatch
    if z_imag is not None:
        x_error = abs(z_imag)
        if x_error > 15:
            severity = "severe" if x_error > 40 else "moderate"
            rtype = "inductive" if z_imag > 0 else "capacitive"
            diagnoses.append(
                Diagnosis(
                    failure_mode=FailureMode.REACTIVE_MISMATCH,
                    severity=severity,
                    detail=(
                        f"Im(Zin) = {z_imag:+.1f} Ω ({rtype}), "
                        f"target 0 Ω (error: {x_error:.1f} Ω)"
                    ),
                    suggested_actions=[
                        f"Add {'series capacitor' if rtype == 'inductive' else 'series inductor'} or adjust geometry",
                        "Modify parameters with REACTANCE_MATCHING role",
                    ],
                )
            )

    # 4. Bandwidth problem
    if bw is not None:
        if bw < 50:  # Less than 50 MHz for typical 2.4 GHz
            diagnoses.append(
                Diagnosis(
                    failure_mode=FailureMode.BANDWIDTH_PROBLEM,
                    severity="moderate" if bw > 20 else "severe",
                    detail=f"Bandwidth = {bw:.1f} MHz (may be insufficient)",
                    suggested_actions=[
                        "Increase substrate height or patch width",
                        "Consider using thicker substrate or lower permittivity",
                    ],
                )
            )

    # 5. Low efficiency
    if eff is not None and eff < 50:
        diagnoses.append(
            Diagnosis(
                failure_mode=FailureMode.LOW_EFFICIENCY,
                severity="severe" if eff < 30 else "moderate",
                detail=f"Efficiency = {eff:.1f}%",
                suggested_actions=[
                    "Check for lossy materials",
                    "Increase ground plane size",
                    "Reduce conductor losses",
                ],
            )
        )

    # 6. Low gain
    if gain is not None and gain < -5:
        diagnoses.append(
            Diagnosis(
                failure_mode=FailureMode.LOW_GAIN,
                severity="moderate",
                detail=f"Gain = {gain:.1f} dBi",
                suggested_actions=[
                    "Check antenna orientation and pattern",
                    "Verify ground plane dimensions",
                ],
            )
        )

    if not diagnoses:
        # Check overall S11
        if s11 is not None and s11 > target_s11_db:
            diagnoses.append(
                Diagnosis(
                    failure_mode=FailureMode.UNKNOWN,
                    severity="minor",
                    detail=f"S11 = {s11:.1f} dB (target: {target_s11_db:.0f} dB)",
                    suggested_actions=[
                        "Run sensitivity analysis to identify critical parameters",
                        "Consider broader parameter sweep",
                    ],
                )
            )

    return diagnoses


@dataclass
class OptimizationSupervisor:
    """Supervises the optimization loop with failure classification.

    Provides deterministic diagnosis and action suggestions.
    Signals NEEDS_AGENT when genuine LLM reasoning is required.
    """

    target_freq_ghz: float = 2.45
    target_s11_db: float = -10.0
    z0: float = 50.0
    max_failed_iterations: int = 5
    _consecutive_failures: int = 0

    def diagnose(
        self,
        sim_result: Any,
        goal: Any = None,
    ) -> list[Diagnosis] | dict[str, Any]:
        """Classify failures in a simulation result."""
        res_dict = {}
        if hasattr(sim_result, "get_value"):
            s11 = sim_result.get_s11_db()
            zin = sim_result.get_impedance()
            if s11 is not None:
                res_dict["s11_db"] = s11
            if zin is not None:
                res_dict["z_real"] = zin[0]
                res_dict["z_imag"] = zin[1]
        elif isinstance(sim_result, dict):
            res_dict = sim_result

        diagnoses = classify_failure(
            res_dict,
            self.target_freq_ghz,
            self.target_s11_db,
            self.z0,
        )
        if goal is not None:
            return {
                "failure_modes": [d.failure_mode for d in diagnoses],
                "suggestions": [act for d in diagnoses for act in d.suggested_actions],
                "diagnoses": [d.to_dict() for d in diagnoses],
            }
        return diagnoses

    def should_continue(
        self,
        iteration: int,
        max_iterations: int,
        best_s11_db: float,
    ) -> dict[str, Any]:
        """Determine if optimization should continue."""
        if best_s11_db <= self.target_s11_db:
            return {
                "continue": False,
                "reason": f"Target S11 ({self.target_s11_db} dB) achieved: {best_s11_db:.1f} dB",
            }
        if iteration >= max_iterations:
            return {
                "continue": False,
                "reason": f"Max iterations ({max_iterations}) reached",
            }
        if self._consecutive_failures >= self.max_failed_iterations:
            return {
                "continue": False,
                "reason": "Too many consecutive failures",
                "needs_agent": True,
            }
        return {"continue": True}

    def record_iteration(self, improved: bool) -> None:
        """Track whether the iteration improved results."""
        if improved:
            self._consecutive_failures = 0
        else:
            self._consecutive_failures += 1
