"""CST runner interface with DryRun, MockCST, and RealCST runners.

Provides a uniform interface for simulation execution with support
for dry-run mode (no computation), mock CST (deterministic synthetic
physics labeled MOCK_SIMULATION), and real CST (COM automation
labeled CST_SIMULATION).
"""

from __future__ import annotations

import logging
import math
import random
import uuid
import hashlib
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


class CSTRunnerBase(ABC):
    """Abstract base for CST simulation runners."""

    @abstractmethod
    def run(
        self,
        parameters: dict[str, float],
        freq_min_ghz: float = 2.0,
        freq_max_ghz: float = 3.0,
    ) -> dict[str, float]:
        """Run a simulation and return results.

        Must return a dict with keys:
          - f_res_ghz: resonant frequency
          - z_real: real part of input impedance
          - z_imag: imaginary part of input impedance
          - s11_db: S11 in dB at resonance
          - bandwidth_mhz: -10 dB bandwidth
          - gain_dbi: peak gain (optional)
          - efficiency_pct: radiation efficiency (optional)
        """
        ...

    @abstractmethod
    def label(self) -> str:
        """Return the provenance label for results."""
        ...

    def cache_identity(self) -> str:
        """Stable identity for result-cache segregation across backends."""
        return self.label()


@dataclass
class DryRunRunner(CSTRunnerBase):
    """Returns placeholder results without any computation.

    Useful for testing the pipeline infrastructure.
    """

    def run(
        self,
        parameters: dict[str, float],
        freq_min_ghz: float = 2.0,
        freq_max_ghz: float = 3.0,
    ) -> dict[str, float]:
        center = (freq_min_ghz + freq_max_ghz) / 2
        return {
            "f_res_ghz": center,
            "z_real": 50.0,
            "z_imag": 0.0,
            "s11_db": -20.0,
            "bandwidth_mhz": 100.0,
            "gain_dbi": 2.0,
            "efficiency_pct": 90.0,
            "source_label": self.label(),
        }

    def label(self) -> str:
        return "DRY_RUN"


# Speed of light (m/s)
_C0 = 299_792_458.0


@dataclass
class MockCSTRunner(CSTRunnerBase):
    """Synthetic physics engine using closed-form EM models."""

    topology: str = "patch"
    seed: int = 42
    center_freq_ghz: float = 2.45

    def run_simulation(self, parameters: dict[str, float]) -> Any:
        res_dict = self.run(parameters, freq_min_ghz=self.center_freq_ghz * 0.9, freq_max_ghz=self.center_freq_ghz * 1.1)
        from ..results import SimulationResult, ResultValue, ResultProvenance
        return SimulationResult(
            execution_id="mock_exec",
            status="complete",
            values=[
                ResultValue(name="s11_db", value=res_dict["s11_db"], unit="dB", provenance=ResultProvenance.MOCK_SIMULATION),
                ResultValue(name="zin_re", value=res_dict["z_real"], unit="Ohm", provenance=ResultProvenance.MOCK_SIMULATION),
                ResultValue(name="zin_im", value=res_dict["z_imag"], unit="Ohm", provenance=ResultProvenance.MOCK_SIMULATION),
            ]
        )

    def run(
        self,
        parameters: dict[str, float],
        freq_min_ghz: float = 2.0,
        freq_max_ghz: float = 3.0,
    ) -> dict[str, float]:
        # Python's built-in hash is randomized per interpreter process.  A
        # SHA-256-derived seed makes mock responses reproducible across runs.
        canonical = repr(sorted(parameters.items())).encode("utf-8")
        offset = int.from_bytes(hashlib.sha256(canonical).digest()[:8], "big")
        rng = random.Random(self.seed + offset)

        if self.topology in ("patch", "pifa"):
            return self._simulate_patch(parameters, freq_min_ghz, freq_max_ghz, rng)
        elif self.topology in ("monopole", "dipole", "ifa"):
            return self._simulate_wire(parameters, freq_min_ghz, freq_max_ghz, rng)
        else:
            return self._simulate_generic(parameters, freq_min_ghz, freq_max_ghz, rng)

    def label(self) -> str:
        return "MOCK_SIMULATION"

    def _simulate_patch(
        self,
        params: dict[str, float],
        freq_min: float,
        freq_max: float,
        rng: random.Random,
    ) -> dict[str, float]:
        # Extract patch parameters
        L = params.get("patch_length_mm", params.get("pifa_length_mm", 29.0))
        W = params.get("patch_width_mm", params.get("pifa_width_mm", 38.0))
        h = params.get("substrate_height_mm", params.get("pifa_height_mm", 1.6))
        er = params.get("er", 4.4)

        # Effective permittivity
        if W > 0 and h > 0:
            er_eff = (er + 1) / 2 + ((er - 1) / 2) * (1 + 12 * h / W) ** (-0.5)
        else:
            er_eff = er

        # Resonant frequency from cavity model
        if L > 0:
            f_res = (_C0 / (2 * L / 1000 * math.sqrt(er_eff))) / 1e9
        else:
            f_res = (freq_min + freq_max) / 2

        # Input impedance (simplified cavity model)
        if W > 0 and L > 0:
            z_edge = 90 * (er ** 2) / (er - 1) * (L / W) ** 2
            # Feed position effect
            feed_offset = params.get("inset_depth_mm", params.get("feed_offset_mm", L * 0.3))
            if L > 0:
                z_real = z_edge * (math.cos(math.pi * feed_offset / L)) ** 2
            else:
                z_real = z_edge
        else:
            z_real = 50.0

        z_real = max(5.0, min(500.0, z_real))

        # Reactance (near resonance, small; off-resonance, increases)
        target_f = (freq_min + freq_max) / 2
        freq_offset = (f_res - target_f) / target_f if target_f > 0 else 0
        z_imag = z_real * 2 * freq_offset * 10  # Simplified Q-factor model

        # S11
        gamma = abs(complex(z_real - 50, z_imag) / complex(z_real + 50, z_imag))
        if gamma > 0:
            s11_db = 20 * math.log10(max(gamma, 1e-10))
        else:
            s11_db = -50.0

        # Bandwidth (Q-factor approximation)
        Q = max(1, z_real / max(1, 2 * h * W / (L if L > 0 else 1)))
        bw_frac = 1 / Q * 100  # as percentage
        bw_mhz = bw_frac / 100 * f_res * 1000

        # Add small noise
        noise = rng.gauss(0, 0.01)
        f_res += noise * f_res

        return {
            "f_res_ghz": round(f_res, 4),
            "z_real": round(z_real, 2),
            "z_imag": round(z_imag, 2),
            "s11_db": round(s11_db, 2),
            "bandwidth_mhz": round(max(1, bw_mhz), 1),
            "gain_dbi": round(5.0 + rng.gauss(0, 0.5), 2),
            "efficiency_pct": round(max(10, min(99, 80 + rng.gauss(0, 5))), 1),
            "source_label": self.label(),
        }

    def _simulate_wire(
        self,
        params: dict[str, float],
        freq_min: float,
        freq_max: float,
        rng: random.Random,
    ) -> dict[str, float]:
        # Wire antenna parameters
        height = params.get(
            "monopole_height_mm",
            params.get(
                "dipole_arm_length_mm",
                params.get("ifa_arm_length_mm", 30.0),
            ),
        )
        radius = params.get("wire_radius_mm", 0.5)

        # Resonant frequency (quarter-wave or half-wave)
        if self.topology in ("monopole", "ifa"):
            f_res = _C0 / (4 * height / 1000) / 1e9
        else:
            f_res = _C0 / (2 * height / 1000) / 1e9

        # Impedance
        if self.topology == "monopole":
            z_real = 36.5  # ~36.5Ω for monopole
        elif self.topology == "dipole":
            z_real = 73.0  # ~73Ω for dipole
        else:
            z_real = 50.0 + rng.gauss(0, 10)

        # Thickness correction for impedance
        if radius > 0 and height > 0:
            thickness_ratio = 2 * radius / height
            z_real *= (1 + 0.5 * math.log(1 / max(thickness_ratio, 0.001)))

        z_real = max(10, min(300, z_real))
        target_f = (freq_min + freq_max) / 2
        freq_offset = (f_res - target_f) / target_f if target_f > 0 else 0
        z_imag = z_real * freq_offset * 5

        gamma = abs(complex(z_real - 50, z_imag) / complex(z_real + 50, z_imag))
        s11_db = 20 * math.log10(max(gamma, 1e-10))

        bw_mhz = 50 + rng.gauss(0, 10)

        return {
            "f_res_ghz": round(f_res, 4),
            "z_real": round(z_real, 2),
            "z_imag": round(z_imag, 2),
            "s11_db": round(s11_db, 2),
            "bandwidth_mhz": round(max(5, bw_mhz), 1),
            "gain_dbi": round(2.15 + rng.gauss(0, 0.3), 2),
            "efficiency_pct": round(max(20, min(99, 90 + rng.gauss(0, 3))), 1),
            "source_label": self.label(),
        }

    def _simulate_generic(
        self,
        params: dict[str, float],
        freq_min: float,
        freq_max: float,
        rng: random.Random,
    ) -> dict[str, float]:
        # Generic: use largest dimension as characteristic length
        dims = [v for k, v in params.items() if "mm" in k.lower() and v > 0]
        char_length = max(dims) if dims else 30.0

        f_res = _C0 / (4 * char_length / 1000) / 1e9
        z_real = 50 + rng.gauss(0, 20)
        z_imag = rng.gauss(0, 15)
        gamma = abs(complex(z_real - 50, z_imag) / complex(z_real + 50, z_imag))
        s11_db = 20 * math.log10(max(gamma, 1e-10))

        return {
            "f_res_ghz": round(f_res, 4),
            "z_real": round(max(5, z_real), 2),
            "z_imag": round(z_imag, 2),
            "s11_db": round(s11_db, 2),
            "bandwidth_mhz": round(max(5, 40 + rng.gauss(0, 10)), 1),
            "gain_dbi": round(2 + rng.gauss(0, 1), 2),
            "efficiency_pct": round(max(10, min(99, 70 + rng.gauss(0, 10))), 1),
            "source_label": self.label(),
        }


@dataclass
class RealCSTRunner(CSTRunnerBase):
    """Real CST COM automation runner.

    Uses CSTBridge to update parameters, run solver, and extract results.
    Results are labeled ``CST_SIMULATION``.
    """

    progid: str = "CSTStudio.Application.2026"
    output_dir: str = ""
    project_path: str = ""
    required_outputs: tuple[str, ...] = (
        "s11_db",
        "f_res_ghz",
        "vswr",
        "zin_re",
        "zin_im",
        "frequency_samples",
    )

    def run_simulation(self, parameters: dict[str, float]) -> Any:
        """Execute CST and return a typed, provenance-preserving result.

        A real run is invalid when CST cannot provide a requested value.  This
        intentionally fails instead of substituting mock or nominal RF values.
        """
        from ..cst_bridge import CSTBridge
        from ..results import normalize_simulation_results

        if not self.project_path:
            raise ValueError("RealCSTRunner requires project_path to be specified.")
        bridge = CSTBridge(progid=self.progid, output_dir=self.output_dir or None)
        bridge.update_parameters(self.project_path, parameters)
        bridge.run_solver(self.project_path)
        response = bridge.extract_results(self.project_path)
        if response.get("status") != "completed":
            raise CSTResultUnavailableError(response.get("error", "CST result export failed."))
        result = normalize_simulation_results(
            execution_id=f"cst-{uuid.uuid4()}",
            extracted=response["extracted"],
            requested_outputs=list(self.required_outputs),
            raw_metadata=response["raw_extracted"],
            derived_outputs={"vswr", "zin_re", "zin_im"},
        )
        if result.missing_requested_outputs:
            unavailable = ", ".join(result.missing_requested_outputs)
            raise CSTResultUnavailableError(
                f"CST did not provide required real outputs: {unavailable}"
            )
        return result

    def run(
        self,
        parameters: dict[str, float],
        freq_min_ghz: float = 2.0,
        freq_max_ghz: float = 3.0,
    ) -> dict[str, float]:
        result = self.run_simulation(parameters)
        values = {value.name: value.value for value in result.values}
        return {
            "f_res_ghz": float(values["f_res_ghz"]),
            "z_real": float(values["zin_re"]),
            "z_imag": float(values["zin_im"]),
            "s11_db": float(values["s11_db"]),
            "vswr": float(values["vswr"]),
            "source_label": self.label(),
            "execution_id": result.execution_id,
        }

    def label(self) -> str:
        return "CST_SIMULATION"

    def cache_identity(self) -> str:
        # A real-project path participates in the cache identity.  This keeps
        # a cached result from a different CST model or backend out of a live
        # optimization run; the model's own materials/settings remain part of
        # the supplied project and must be checkpointed by the caller.
        return f"{self.label()}|{self.progid}|{self.project_path}"


class CSTResultUnavailableError(RuntimeError):
    """Raised when a CST execution lacks a required verified output."""
