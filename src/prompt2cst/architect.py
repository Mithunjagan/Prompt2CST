"""RF Architecture Agent - multi-candidate topology evaluation.

Generates and scores multiple antenna candidate topologies for a
given set of requirements, performs closed-form equation-based
sizing tailored to each topology, and selects the best candidate.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from .antenna_knowledge import family_evidence

logger = logging.getLogger(__name__)

# Speed of light (m/s)
C0 = 299_792_458.0


class AntennaTopology(StrEnum):
    PATCH = "patch"
    PIFA = "pifa"
    IFA = "ifa"
    MONOPOLE = "monopole"
    DIPOLE = "dipole"
    SLOT = "slot"
    LOOP = "loop"
    MEANDER = "meander"
    FRAME_INTEGRATED = "frame_integrated"
    TRANSPARENT = "transparent"
    HELIX = "helix"
    YAGI_UDA = "yagi_uda"
    HORN = "horn"
    VIVALDI = "vivaldi"


@dataclass(frozen=True)
class TopologyScore:
    """Scoring of a candidate topology on multiple criteria."""

    topology: AntennaTopology
    frequency_score: float  # 0-1, how well it covers the band
    volume_score: float  # 0-1, lower volume = higher score
    bandwidth_score: float  # 0-1, expected bandwidth coverage
    matching_score: float  # 0-1, ease of impedance matching
    efficiency_score: float  # 0-1, expected radiation efficiency
    manufacturability_score: float  # 0-1, ease of fabrication
    overall: float = 0.0
    rationale: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "topology": self.topology,
            "frequency_score": round(self.frequency_score, 3),
            "volume_score": round(self.volume_score, 3),
            "bandwidth_score": round(self.bandwidth_score, 3),
            "matching_score": round(self.matching_score, 3),
            "efficiency_score": round(self.efficiency_score, 3),
            "manufacturability_score": round(self.manufacturability_score, 3),
            "overall": round(self.overall, 3),
            "rationale": self.rationale,
        }


@dataclass(frozen=True)
class InitialSizing:
    """Equation-driven initial dimensions for a topology."""

    topology: AntennaTopology
    parameters: dict[str, float]  # name -> value in mm
    equations_used: list[str]
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "topology": self.topology,
            "parameters": self.parameters,
            "equations_used": self.equations_used,
            "notes": list(self.notes),
        }


# Topology-specific knowledge base for scoring
_TOPOLOGY_PROFILES: dict[AntennaTopology, dict[str, float]] = {
    AntennaTopology.PATCH: {
        "bw_ratio": 0.03,  # ~3% typical BW
        "volume_factor": 0.7,
        "matching_ease": 0.8,
        "efficiency_base": 0.85,
        "mfg_ease": 0.9,
        "min_freq_ghz": 0.5,
        "max_freq_ghz": 100.0,
    },
    AntennaTopology.PIFA: {
        "bw_ratio": 0.05,
        "volume_factor": 0.4,
        "matching_ease": 0.7,
        "efficiency_base": 0.6,
        "mfg_ease": 0.7,
        "min_freq_ghz": 0.8,
        "max_freq_ghz": 10.0,
    },
    AntennaTopology.IFA: {
        "bw_ratio": 0.06,
        "volume_factor": 0.35,
        "matching_ease": 0.75,
        "efficiency_base": 0.55,
        "mfg_ease": 0.8,
        "min_freq_ghz": 0.8,
        "max_freq_ghz": 10.0,
    },
    AntennaTopology.MONOPOLE: {
        "bw_ratio": 0.15,
        "volume_factor": 0.5,
        "matching_ease": 0.85,
        "efficiency_base": 0.9,
        "mfg_ease": 0.95,
        "min_freq_ghz": 0.1,
        "max_freq_ghz": 30.0,
    },
    AntennaTopology.DIPOLE: {
        "bw_ratio": 0.12,
        "volume_factor": 0.6,
        "matching_ease": 0.85,
        "efficiency_base": 0.95,
        "mfg_ease": 0.9,
        "min_freq_ghz": 0.1,
        "max_freq_ghz": 30.0,
    },
    AntennaTopology.SLOT: {
        "bw_ratio": 0.04,
        "volume_factor": 0.45,
        "matching_ease": 0.65,
        "efficiency_base": 0.7,
        "mfg_ease": 0.75,
        "min_freq_ghz": 0.5,
        "max_freq_ghz": 30.0,
    },
    AntennaTopology.LOOP: {
        "bw_ratio": 0.02,
        "volume_factor": 0.3,
        "matching_ease": 0.5,
        "efficiency_base": 0.4,
        "mfg_ease": 0.85,
        "min_freq_ghz": 0.01,
        "max_freq_ghz": 10.0,
    },
    AntennaTopology.MEANDER: {
        "bw_ratio": 0.04,
        "volume_factor": 0.25,
        "matching_ease": 0.6,
        "efficiency_base": 0.5,
        "mfg_ease": 0.7,
        "min_freq_ghz": 0.5,
        "max_freq_ghz": 6.0,
    },
    AntennaTopology.FRAME_INTEGRATED: {
        "bw_ratio": 0.05,
        "volume_factor": 0.15,
        "matching_ease": 0.55,
        "efficiency_base": 0.45,
        "mfg_ease": 0.5,
        "min_freq_ghz": 0.8,
        "max_freq_ghz": 6.0,
    },
    AntennaTopology.TRANSPARENT: {
        "bw_ratio": 0.03,
        "volume_factor": 0.5,
        "matching_ease": 0.55,
        "efficiency_base": 0.5,
        "mfg_ease": 0.4,
        "min_freq_ghz": 0.8,
        "max_freq_ghz": 6.0,
    },
    AntennaTopology.HELIX: {
        "bw_ratio": 0.35, "volume_factor": 0.9, "matching_ease": 0.55,
        "efficiency_base": 0.8, "mfg_ease": 0.6,
        "min_freq_ghz": 0.1, "max_freq_ghz": 30.0,
    },
    AntennaTopology.YAGI_UDA: {
        "bw_ratio": 0.08, "volume_factor": 0.95, "matching_ease": 0.65,
        "efficiency_base": 0.9, "mfg_ease": 0.7,
        "min_freq_ghz": 0.03, "max_freq_ghz": 10.0,
    },
    AntennaTopology.HORN: {
        "bw_ratio": 0.35, "volume_factor": 1.0, "matching_ease": 0.8,
        "efficiency_base": 0.92, "mfg_ease": 0.55,
        "min_freq_ghz": 1.0, "max_freq_ghz": 300.0,
    },
    AntennaTopology.VIVALDI: {
        "bw_ratio": 0.8, "volume_factor": 0.85, "matching_ease": 0.65,
        "efficiency_base": 0.75, "mfg_ease": 0.8,
        "min_freq_ghz": 0.3, "max_freq_ghz": 110.0,
    },
}


def _score_topology(
    topology: AntennaTopology,
    freq_center_ghz: float,
    bandwidth_needed_ghz: float,
    volume_mm3: float | None = None,
    weights: dict[str, float] | None = None,
) -> TopologyScore:
    """Score a topology for the given requirements."""
    profile = _TOPOLOGY_PROFILES[topology]
    w = weights or {
        "frequency": 0.20,
        "volume": 0.15,
        "bandwidth": 0.25,
        "matching": 0.15,
        "efficiency": 0.15,
        "manufacturability": 0.10,
    }

    # Frequency score
    in_range = profile["min_freq_ghz"] <= freq_center_ghz <= profile["max_freq_ghz"]
    freq_score = 1.0 if in_range else 0.1

    # Bandwidth score
    expected_bw = profile["bw_ratio"] * freq_center_ghz
    bw_score = min(1.0, expected_bw / max(bandwidth_needed_ghz, 0.001))

    # Volume score
    wavelength_mm = (C0 / (freq_center_ghz * 1e9)) * 1000
    if volume_mm3 is not None:
        relative_vol = volume_mm3 / (wavelength_mm ** 3)
        vol_score = max(0, 1.0 - profile["volume_factor"] * relative_vol * 10)
    else:
        vol_score = 1.0 - profile["volume_factor"]

    matching_score = profile["matching_ease"]
    efficiency_score = profile["efficiency_base"]
    mfg_score = profile["mfg_ease"]

    overall = (
        w["frequency"] * freq_score
        + w["volume"] * vol_score
        + w["bandwidth"] * bw_score
        + w["matching"] * matching_score
        + w["efficiency"] * efficiency_score
        + w["manufacturability"] * mfg_score
    )

    rationale_parts = []
    if freq_score < 0.5:
        rationale_parts.append(f"Frequency {freq_center_ghz} GHz outside typical range")
    if bw_score < 0.5:
        rationale_parts.append("May not achieve required bandwidth")
    if efficiency_score > 0.7:
        rationale_parts.append("Good expected efficiency")
    if vol_score > 0.7:
        rationale_parts.append("Compact form factor")

    return TopologyScore(
        topology=topology,
        frequency_score=freq_score,
        volume_score=vol_score,
        bandwidth_score=bw_score,
        matching_score=matching_score,
        efficiency_score=efficiency_score,
        manufacturability_score=mfg_score,
        overall=overall,
        rationale="; ".join(rationale_parts) if rationale_parts else "Standard candidate",
    )


def _size_patch(freq_ghz: float, er: float = 4.4, h_mm: float = 1.6) -> InitialSizing:
    """Closed-form patch sizing (Balanis equations)."""
    f = freq_ghz * 1e9
    lam0 = C0 / f
    lam0_mm = lam0 * 1000

    # Patch width
    W = (C0 / (2 * f)) * math.sqrt(2 / (er + 1))
    W_mm = W * 1000

    # Effective permittivity
    er_eff = (er + 1) / 2 + ((er - 1) / 2) * (1 + 12 * (h_mm / 1000) / W) ** (-0.5)

    # Length extension
    dL = (
        0.412
        * (h_mm / 1000)
        * ((er_eff + 0.3) * (W_mm / 1000 / (h_mm / 1000) + 0.264))
        / ((er_eff - 0.258) * (W_mm / 1000 / (h_mm / 1000) + 0.8))
    )
    dL_mm = dL * 1000

    # Patch length
    L_eff = C0 / (2 * f * math.sqrt(er_eff))
    L_mm = L_eff * 1000 - 2 * dL_mm

    # Ground plane
    gnd_L = L_mm + 6 * h_mm
    gnd_W = W_mm + 6 * h_mm

    return InitialSizing(
        topology=AntennaTopology.PATCH,
        parameters={
            "patch_width_mm": round(W_mm, 3),
            "patch_length_mm": round(L_mm, 3),
            "substrate_height_mm": h_mm,
            "ground_length_mm": round(gnd_L, 3),
            "ground_width_mm": round(gnd_W, 3),
            "er_eff": round(er_eff, 4),
        },
        equations_used=[
            "W = c0 / (2f) * sqrt(2/(er+1))",
            "er_eff = (er+1)/2 + (er-1)/2 * (1+12h/W)^(-0.5)",
            "dL = 0.412*h*(er_eff+0.3)*(W/h+0.264)/((er_eff-0.258)*(W/h+0.8))",
            "L = c0/(2f*sqrt(er_eff)) - 2*dL",
        ],
        notes=["Balanis rectangular patch equations"],
    )


def _size_pifa(freq_ghz: float, h_mm: float = 5.0) -> InitialSizing:
    """PIFA sizing: L + W ≈ λ/4."""
    lam_mm = (C0 / (freq_ghz * 1e9)) * 1000
    quarter_lam = lam_mm / 4

    # Typical PIFA: L + W ≈ λ/4, with L ≈ 0.6 * quarter_lam
    L = 0.6 * quarter_lam
    W = quarter_lam - L

    return InitialSizing(
        topology=AntennaTopology.PIFA,
        parameters={
            "pifa_length_mm": round(L, 3),
            "pifa_width_mm": round(W, 3),
            "pifa_height_mm": h_mm,
            "shorting_width_mm": round(W * 0.1, 3),
            "feed_offset_mm": round(L * 0.3, 3),
            "ground_length_mm": round(L + 10, 3),
            "ground_width_mm": round(W + 10, 3),
        },
        equations_used=[
            "L + W ≈ λ/4",
            "shorting_width ≈ 0.1 * W (initial estimate)",
            "feed_offset ≈ 0.3 * L (50Ω match estimate)",
        ],
        notes=["PIFA quarter-wave resonance condition"],
    )


def _size_ifa(freq_ghz: float, h_mm: float = 3.0) -> InitialSizing:
    """IFA sizing: total meander length ≈ λ/4."""
    lam_mm = (C0 / (freq_ghz * 1e9)) * 1000
    quarter_lam = lam_mm / 4

    return InitialSizing(
        topology=AntennaTopology.IFA,
        parameters={
            "ifa_total_length_mm": round(quarter_lam, 3),
            "ifa_height_mm": h_mm,
            "ifa_arm_length_mm": round(quarter_lam - h_mm, 3),
            "shorting_to_feed_mm": round(quarter_lam * 0.08, 3),
            "ground_length_mm": round(quarter_lam + 10, 3),
            "ground_width_mm": round(quarter_lam * 0.5, 3),
        },
        equations_used=[
            "total_length ≈ λ/4",
            "arm_length = total_length - height",
            "shorting_to_feed ≈ 0.08 * λ/4 (50Ω match estimate)",
        ],
        notes=["IFA quarter-wave resonance condition"],
    )


def _size_monopole(freq_ghz: float, wire_radius_mm: float = 0.5) -> InitialSizing:
    """Quarter-wave monopole sizing."""
    lam_mm = (C0 / (freq_ghz * 1e9)) * 1000
    quarter_lam = lam_mm / 4
    ground_radius = lam_mm / 4

    return InitialSizing(
        topology=AntennaTopology.MONOPOLE,
        parameters={
            "monopole_height_mm": round(quarter_lam, 3),
            "wire_radius_mm": wire_radius_mm,
            "ground_radius_mm": round(ground_radius, 3),
        },
        equations_used=["height = λ/4", "ground_radius ≈ λ/4"],
        notes=["Quarter-wave monopole over ground plane"],
    )


def _size_dipole(freq_ghz: float, wire_radius_mm: float = 0.5) -> InitialSizing:
    """Half-wave dipole sizing."""
    lam_mm = (C0 / (freq_ghz * 1e9)) * 1000
    half_lam = lam_mm / 2

    return InitialSizing(
        topology=AntennaTopology.DIPOLE,
        parameters={
            "dipole_total_length_mm": round(half_lam, 3),
            "dipole_arm_length_mm": round(half_lam / 2, 3),
            "wire_radius_mm": wire_radius_mm,
            "gap_mm": round(wire_radius_mm * 2, 3),
        },
        equations_used=["total_length = λ/2", "arm = λ/4"],
        notes=["Half-wave center-fed dipole"],
    )


def _size_meander(freq_ghz: float, max_length_mm: float = 20.0) -> InitialSizing:
    """Meander-line antenna sizing."""
    lam_mm = (C0 / (freq_ghz * 1e9)) * 1000
    quarter_lam = lam_mm / 4

    # Number of meander sections needed
    meander_height = 2.0  # mm
    n_sections = max(2, int(math.ceil(quarter_lam / max_length_mm)))
    segment_length = quarter_lam / n_sections

    return InitialSizing(
        topology=AntennaTopology.MEANDER,
        parameters={
            "total_wire_length_mm": round(quarter_lam, 3),
            "meander_sections": n_sections,
            "segment_length_mm": round(segment_length, 3),
            "meander_height_mm": meander_height,
            "overall_length_mm": round(min(max_length_mm, quarter_lam), 3),
            "trace_width_mm": 0.5,
        },
        equations_used=[
            "total_wire_length ≈ λ/4",
            "n_sections = ceil(λ/4 / max_length)",
        ],
        notes=["Meander shortens physical length while maintaining electrical length"],
    )


_SIZING_FUNCTIONS = {
    AntennaTopology.PATCH: _size_patch,
    AntennaTopology.PIFA: _size_pifa,
    AntennaTopology.IFA: _size_ifa,
    AntennaTopology.MONOPOLE: _size_monopole,
    AntennaTopology.DIPOLE: _size_dipole,
    AntennaTopology.MEANDER: _size_meander,
}


@dataclass
class RFArchitectureAgent:
    """Evaluates and selects antenna topologies deterministically.

    Scores candidates on frequency coverage, volume, bandwidth,
    matching difficulty, efficiency, and manufacturability.
    """

    def evaluate_candidates(
        self,
        freq_min_ghz: float,
        freq_max_ghz: float,
        volume_mm3: float | None = None,
        topologies: list[AntennaTopology] | None = None,
        weights: dict[str, float] | None = None,
    ) -> list[TopologyScore]:
        """Score all (or specified) topologies for the given requirements."""
        freq_center = (freq_min_ghz + freq_max_ghz) / 2
        bw_needed = freq_max_ghz - freq_min_ghz

        candidates = topologies or list(AntennaTopology)
        scores = [
            _score_topology(t, freq_center, bw_needed, volume_mm3, weights)
            for t in candidates
        ]
        scores.sort(key=lambda s: s.overall, reverse=True)
        return scores

    def select_best(
        self,
        freq_min_ghz: float,
        freq_max_ghz: float,
        volume_mm3: float | None = None,
        topologies: list[AntennaTopology] | None = None,
        weights: dict[str, float] | None = None,
    ) -> TopologyScore:
        """Select the best-scoring topology."""
        candidates = self.evaluate_candidates(
            freq_min_ghz, freq_max_ghz, volume_mm3, topologies, weights
        )
        return candidates[0]

    def compute_initial_sizing(
        self,
        topology: AntennaTopology,
        freq_ghz: float,
        **kwargs: Any,
    ) -> InitialSizing:
        """Compute equation-driven initial dimensions for a topology."""
        sizing_fn = _SIZING_FUNCTIONS.get(topology)
        if sizing_fn is None:
            # Generic quarter-wave fallback
            lam_mm = (C0 / (freq_ghz * 1e9)) * 1000
            return InitialSizing(
                topology=topology,
                parameters={
                    "characteristic_length_mm": round(lam_mm / 4, 3),
                    "wavelength_mm": round(lam_mm, 3),
                },
                equations_used=["characteristic_length ≈ λ/4"],
                notes=[f"Generic sizing for {topology} - refine with simulation"],
            )
        return sizing_fn(freq_ghz, **kwargs)

    def full_evaluation(
        self,
        freq_min_ghz: float,
        freq_max_ghz: float,
        volume_mm3: float | None = None,
        topologies: list[AntennaTopology] | None = None,
    ) -> dict[str, Any]:
        """Perform full evaluation: score, select, and size."""
        candidates = self.evaluate_candidates(
            freq_min_ghz, freq_max_ghz, volume_mm3, topologies
        )
        best = candidates[0]
        freq_center = (freq_min_ghz + freq_max_ghz) / 2
        sizing = self.compute_initial_sizing(best.topology, freq_center)
        try:
            evidence: dict[str, Any] | None = family_evidence(str(best.topology))
        except KeyError:
            evidence = None

        return {
            "candidates": [c.to_dict() for c in candidates],
            "selected": best.to_dict(),
            "initial_sizing": sizing.to_dict(),
            "frequency_range_ghz": [freq_min_ghz, freq_max_ghz],
            "knowledge_evidence": evidence,
        }

    def evaluate_topologies(self, reqs: dict[str, Any]) -> dict[str, Any]:
        """Evaluate topologies from a requirements dictionary."""
        f_center = reqs.get("center_frequency_hz", 2.45e9) / 1e9
        f_min = reqs.get("frequency_min_hz", f_center * 0.95 * 1e9) / 1e9
        f_max = reqs.get("frequency_max_hz", f_center * 1.05 * 1e9) / 1e9
        vol = reqs.get("max_volume_mm3")

        eval_res = self.full_evaluation(f_min, f_max, vol)
        selected = eval_res["selected"]
        sizing = eval_res["initial_sizing"]

        return {
            "candidates": eval_res["candidates"],
            "recommended": {
                "topology": selected["topology"],
                "score": selected["overall"],
                "closed_form_dimensions": sizing["parameters"],
            },
        }
