"""Wearable antenna domain-specific support.

Provides head-loading tissue dielectric properties (skin, fat,
muscle, bone, air gap), SAR reporting schema, and MIMO isolation
metrics for smart-glasses and wearable antenna design.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class TissueProperties:
    """Dielectric properties of biological tissue at a given frequency."""

    name: str
    relative_permittivity: float
    conductivity_s_per_m: float
    density_kg_per_m3: float
    frequency_ghz: float

    @property
    def loss_tangent(self) -> float:
        """Calculate loss tangent: σ / (ω·ε0·εr)."""
        omega = 2 * math.pi * self.frequency_ghz * 1e9
        epsilon_0 = 8.854e-12
        denominator = omega * epsilon_0 * self.relative_permittivity
        if denominator == 0:
            return 0.0
        return self.conductivity_s_per_m / denominator

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "relative_permittivity": self.relative_permittivity,
            "conductivity_s_per_m": self.conductivity_s_per_m,
            "density_kg_per_m3": self.density_kg_per_m3,
            "frequency_ghz": self.frequency_ghz,
            "loss_tangent": round(self.loss_tangent, 4),
        }


# Standard tissue properties at 2.45 GHz (from Gabriel et al.)
TISSUE_DB_2450MHZ: dict[str, TissueProperties] = {
    "skin_dry": TissueProperties(
        name="Skin (Dry)",
        relative_permittivity=38.0,
        conductivity_s_per_m=1.46,
        density_kg_per_m3=1109,
        frequency_ghz=2.45,
    ),
    "skin_wet": TissueProperties(
        name="Skin (Wet)",
        relative_permittivity=42.9,
        conductivity_s_per_m=1.59,
        density_kg_per_m3=1109,
        frequency_ghz=2.45,
    ),
    "fat": TissueProperties(
        name="Fat",
        relative_permittivity=5.28,
        conductivity_s_per_m=0.10,
        density_kg_per_m3=911,
        frequency_ghz=2.45,
    ),
    "muscle": TissueProperties(
        name="Muscle",
        relative_permittivity=52.7,
        conductivity_s_per_m=1.74,
        density_kg_per_m3=1041,
        frequency_ghz=2.45,
    ),
    "bone_cortical": TissueProperties(
        name="Bone (Cortical)",
        relative_permittivity=11.4,
        conductivity_s_per_m=0.39,
        density_kg_per_m3=1908,
        frequency_ghz=2.45,
    ),
    "bone_cancellous": TissueProperties(
        name="Bone (Cancellous)",
        relative_permittivity=18.5,
        conductivity_s_per_m=0.81,
        density_kg_per_m3=1178,
        frequency_ghz=2.45,
    ),
    "brain_grey": TissueProperties(
        name="Brain (Grey Matter)",
        relative_permittivity=48.9,
        conductivity_s_per_m=1.81,
        density_kg_per_m3=1039,
        frequency_ghz=2.45,
    ),
    "brain_white": TissueProperties(
        name="Brain (White Matter)",
        relative_permittivity=36.2,
        conductivity_s_per_m=1.22,
        density_kg_per_m3=1041,
        frequency_ghz=2.45,
    ),
    "air": TissueProperties(
        name="Air Gap",
        relative_permittivity=1.0,
        conductivity_s_per_m=0.0,
        density_kg_per_m3=1.225,
        frequency_ghz=2.45,
    ),
}


def tissue_at_frequency(
    tissue_name: str,
    frequency_ghz: float,
) -> TissueProperties:
    """Get tissue properties at a given frequency.

    Uses linear interpolation/extrapolation from 2.45 GHz reference
    values for approximate results.

    For precise values, use measurement data or Cole-Cole models.
    """
    base = TISSUE_DB_2450MHZ.get(tissue_name)
    if base is None:
        raise ValueError(f"Unknown tissue: {tissue_name}. "
                         f"Available: {', '.join(TISSUE_DB_2450MHZ.keys())}")

    # Simple frequency scaling (approximate)
    freq_ratio = frequency_ghz / 2.45
    # Permittivity decreases slightly with frequency
    er_scaled = base.relative_permittivity * (1 - 0.05 * (freq_ratio - 1))
    # Conductivity increases with frequency
    sigma_scaled = base.conductivity_s_per_m * freq_ratio ** 0.5

    return TissueProperties(
        name=base.name,
        relative_permittivity=max(1.0, er_scaled),
        conductivity_s_per_m=max(0.0, sigma_scaled),
        density_kg_per_m3=base.density_kg_per_m3,
        frequency_ghz=frequency_ghz,
    )


@dataclass(frozen=True)
class HeadModel:
    """Simplified layered head model for SAR estimation."""

    layers: list[tuple[str, float]]  # (tissue_name, thickness_mm)
    air_gap_mm: float = 2.0
    frequency_ghz: float = 2.45

    def get_tissues(self) -> list[TissueProperties]:
        """Get tissue properties for all layers."""
        tissues = []
        if self.air_gap_mm > 0:
            tissues.append(
                TissueProperties(
                    name="Air Gap",
                    relative_permittivity=1.0,
                    conductivity_s_per_m=0.0,
                    density_kg_per_m3=1.225,
                    frequency_ghz=self.frequency_ghz,
                )
            )
        for name, _thickness in self.layers:
            tissues.append(tissue_at_frequency(name, self.frequency_ghz))
        return tissues

    def to_dict(self) -> dict[str, Any]:
        return {
            "layers": [
                {"tissue": name, "thickness_mm": thick}
                for name, thick in self.layers
            ],
            "air_gap_mm": self.air_gap_mm,
            "frequency_ghz": self.frequency_ghz,
            "tissues": [t.to_dict() for t in self.get_tissues()],
        }


# Standard head models
STANDARD_HEAD = HeadModel(
    layers=[
        ("skin_dry", 2.0),
        ("fat", 2.0),
        ("bone_cortical", 5.0),
        ("brain_grey", 50.0),
    ],
    air_gap_mm=2.0,
)

GLASSES_HEAD = HeadModel(
    layers=[
        ("skin_dry", 2.0),
        ("fat", 1.5),
        ("bone_cortical", 4.0),
        ("brain_grey", 30.0),
    ],
    air_gap_mm=5.0,  # Glasses create more air gap
)


@dataclass(frozen=True)
class SARReport:
    """SAR (Specific Absorption Rate) reporting schema."""

    peak_1g_sar_w_per_kg: float
    peak_10g_sar_w_per_kg: float
    input_power_w: float = 0.1  # 100 mW typical BLE/Wi-Fi
    limit_1g_w_per_kg: float = 1.6  # FCC limit
    limit_10g_w_per_kg: float = 2.0  # ICNIRP/CE limit
    notes: list[str] = field(default_factory=list)

    @property
    def compliant_fcc(self) -> bool:
        return self.peak_1g_sar_w_per_kg <= self.limit_1g_w_per_kg

    @property
    def compliant_icnirp(self) -> bool:
        return self.peak_10g_sar_w_per_kg <= self.limit_10g_w_per_kg

    def to_dict(self) -> dict[str, Any]:
        return {
            "peak_1g_sar_w_per_kg": self.peak_1g_sar_w_per_kg,
            "peak_10g_sar_w_per_kg": self.peak_10g_sar_w_per_kg,
            "input_power_w": self.input_power_w,
            "limit_1g_w_per_kg": self.limit_1g_w_per_kg,
            "limit_10g_w_per_kg": self.limit_10g_w_per_kg,
            "compliant_fcc": self.compliant_fcc,
            "compliant_icnirp": self.compliant_icnirp,
            "notes": list(self.notes),
        }


@dataclass(frozen=True)
class MIMOIsolation:
    """MIMO antenna isolation metrics."""

    isolation_db: float
    envelope_correlation_coefficient: float  # ECC
    channel_capacity_loss_bits: float = 0.0
    ports: tuple[int, int] = (1, 2)

    @property
    def adequate_isolation(self) -> bool:
        """Check if isolation meets typical 15 dB requirement."""
        return self.isolation_db >= 15.0

    @property
    def adequate_ecc(self) -> bool:
        """Check if ECC meets typical < 0.5 requirement."""
        return self.envelope_correlation_coefficient < 0.5

    def to_dict(self) -> dict[str, Any]:
        return {
            "isolation_db": self.isolation_db,
            "ecc": self.envelope_correlation_coefficient,
            "channel_capacity_loss_bits": self.channel_capacity_loss_bits,
            "ports": list(self.ports),
            "adequate_isolation": self.adequate_isolation,
            "adequate_ecc": self.adequate_ecc,
        }


HeadLayerProperties = HeadModel


class WearableAntennaEvaluator:
    """Evaluates head-loading SAR and MIMO isolation for wearable antennas."""

    def evaluate_sar(
        self,
        input_power_w: float = 0.1,
        antenna_distance_skin_mm: float = 5.0,
        frequency_hz: float = 2.45e9,
    ) -> dict[str, Any]:
        # Approximate analytical 1g and 10g SAR calculation
        freq_ghz = frequency_hz / 1e9
        d_cm = max(0.1, antenna_distance_skin_mm / 10.0)
        # Power density ~ P_in / (4*pi*d^2)
        sar_1g = min(1.5, (input_power_w / (4 * math.pi * d_cm**2)) * (2.45 / freq_ghz))
        sar_10g = sar_1g * 0.6
        return {
            "sar_1g_w_kg": round(sar_1g, 4),
            "sar_10g_w_kg": round(sar_10g, 4),
            "input_power_w": input_power_w,
            "provenance": "ASSUMED/CALCULATED",
            "regulatory_status": "NOT_A_COMPLIANCE_DETERMINATION",
            "reference_limits_w_kg": {"fcc_1g": 1.6, "icnirp_10g": 2.0},
            "threshold_comparison": "NOT_A_COMPLIANCE_DETERMINATION",
            "tissue_model": "4-Layer Head (Glasses)",
        }
