"""Optimization goal schemas for impedance-matching optimization.

Defines the objective function structure including reference impedance,
complex impedance error, normalized impedance error, multi-objective
weighting, and frequency range evaluation.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class ObjectiveMetric(StrEnum):
    S11_DB = "s11_db"
    VSWR = "vswr"
    IMPEDANCE_ERROR = "impedance_error"
    NORMALIZED_IMPEDANCE_ERROR = "normalized_impedance_error"
    GAIN_DBI = "gain_dbi"
    EFFICIENCY = "efficiency"
    BANDWIDTH_MHZ = "bandwidth_mhz"
    RESONANCE_OFFSET_MHZ = "resonance_offset_mhz"


class ObjectiveDirection(StrEnum):
    MINIMIZE = "minimize"
    MAXIMIZE = "maximize"


@dataclass(frozen=True)
class OptimizationObjective:
    """A single objective in the optimization."""

    metric: ObjectiveMetric
    direction: ObjectiveDirection = ObjectiveDirection.MINIMIZE
    target: float | None = None
    weight: float = 1.0
    frequency_ghz: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "metric": self.metric,
            "direction": self.direction,
            "target": self.target,
            "weight": self.weight,
            "frequency_ghz": self.frequency_ghz,
        }


@dataclass(frozen=True)
class FrequencyRange:
    """Frequency range for evaluation."""

    min_ghz: float
    max_ghz: float
    n_points: int = 101
    center_ghz: float | None = None

    def __post_init__(self) -> None:
        if self.max_ghz <= self.min_ghz:
            raise ValueError("max_ghz must be greater than min_ghz")
        if self.center_ghz is None:
            object.__setattr__(self, "center_ghz", (self.min_ghz + self.max_ghz) / 2)
        elif not self.min_ghz <= self.center_ghz <= self.max_ghz:
            raise ValueError("center_ghz must lie within the frequency range")

    @property
    def bandwidth_ghz(self) -> float:
        return self.max_ghz - self.min_ghz

    def frequencies_ghz(self) -> list[float]:
        if self.n_points <= 1:
            return [self.center_ghz]
        step = self.bandwidth_ghz / (self.n_points - 1)
        return [self.min_ghz + i * step for i in range(self.n_points)]


@dataclass
class OptimizationGoalSchema:
    """Full optimization goal specification.

    Defines the impedance reference, objectives, frequency range,
    and convergence criteria.
    """

    reference_impedance_ohm: float = 50.0
    frequency_range: FrequencyRange = field(
        default_factory=lambda: FrequencyRange(2.40, 2.50)
    )
    objectives: list[OptimizationObjective] = field(default_factory=list)
    max_iterations: int = 50
    convergence_threshold: float = 0.01
    early_stop_s11_db: float = -15.0

    def __post_init__(self) -> None:
        if not self.objectives:
            # Default: minimize S11 at center frequency
            self.objectives = [
                OptimizationObjective(
                    metric=ObjectiveMetric.S11_DB,
                    direction=ObjectiveDirection.MINIMIZE,
                    target=-10.0,
                    weight=1.0,
                    frequency_ghz=self.frequency_range.center_ghz,
                ),
            ]

    def to_dict(self) -> dict[str, Any]:
        return {
            "reference_impedance_ohm": self.reference_impedance_ohm,
            "frequency_range": {
                "min_ghz": self.frequency_range.min_ghz,
                "max_ghz": self.frequency_range.max_ghz,
                "n_points": self.frequency_range.n_points,
            },
            "objectives": [o.to_dict() for o in self.objectives],
            "max_iterations": self.max_iterations,
            "convergence_threshold": self.convergence_threshold,
            "early_stop_s11_db": self.early_stop_s11_db,
        }


# ------------------------------------------------------------------
# Impedance error functions
# ------------------------------------------------------------------


def impedance_error(
    z_real: float,
    z_imag: float,
    z0: float = 50.0,
) -> float:
    """Absolute impedance error: sqrt((Re(Zin)-Z0)^2 + (Im(Zin)-0)^2)."""
    return math.sqrt((z_real - z0) ** 2 + z_imag ** 2)


def normalized_impedance_error(
    z_real: float,
    z_imag: float,
    z0: float = 50.0,
) -> float:
    """Normalized impedance error relative to Z0."""
    return impedance_error(z_real, z_imag, z0) / z0


def reflection_coefficient(
    z_real: float,
    z_imag: float,
    z0: float = 50.0,
) -> complex:
    """Complex reflection coefficient Γ = (Zin - Z0) / (Zin + Z0)."""
    z_in = complex(z_real, z_imag)
    z_ref = complex(z0, 0)
    if abs(z_in + z_ref) < 1e-12:
        return complex(1.0, 0.0)
    return (z_in - z_ref) / (z_in + z_ref)


def s11_from_impedance(
    z_real: float,
    z_imag: float,
    z0: float = 50.0,
) -> float:
    """S11 in dB from input impedance."""
    gamma = reflection_coefficient(z_real, z_imag, z0)
    mag = abs(gamma)
    if mag == 0:
        return -float("inf")
    return 20.0 * math.log10(mag)
@dataclass
class ParameterBound:
    name: str
    min_value: float
    max_value: float
    default_value: float = 0.0


OptimizationGoalConfig = OptimizationGoalSchema


def compute_impedance_error(
    zin_re: float,
    zin_im: float,
    target_re: float = 50.0,
    target_im: float = 0.0,
) -> float:
    return math.sqrt((zin_re - target_re) ** 2 + (zin_im - target_im) ** 2)
