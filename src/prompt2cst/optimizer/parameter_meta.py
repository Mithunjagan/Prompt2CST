"""Parameter role metadata and topology-specific role inference.

Maps each optimization parameter to its physical role (resonance,
resistance matching, reactance matching, bandwidth, coupling, etc.)
so the staged optimizer can prioritize parameters appropriately.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class ParameterRole(StrEnum):
    RESONANCE = "resonance"
    RESISTANCE_MATCHING = "resistance_matching"
    REACTANCE_MATCHING = "reactance_matching"
    BANDWIDTH = "bandwidth"
    COUPLING = "coupling"
    GAIN = "gain"
    EFFICIENCY = "efficiency"
    GEOMETRY = "geometry"


@dataclass(frozen=True)
class ParameterMeta:
    """Metadata for a single optimization parameter."""

    name: str
    role: ParameterRole
    sensitivity_rank: int = 0  # 0 = unknown, 1 = most sensitive
    description: str = ""
    min_value: float | None = None
    max_value: float | None = None
    step_size: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "role": self.role,
            "sensitivity_rank": self.sensitivity_rank,
            "description": self.description,
            "min_value": self.min_value,
            "max_value": self.max_value,
            "step_size": self.step_size,
        }


# Topology-specific role mappings
_PATCH_ROLES: dict[str, ParameterRole] = {
    "patch_length": ParameterRole.RESONANCE,
    "patch_length_mm": ParameterRole.RESONANCE,
    "patch_width": ParameterRole.BANDWIDTH,
    "patch_width_mm": ParameterRole.BANDWIDTH,
    "substrate_height": ParameterRole.BANDWIDTH,
    "substrate_height_mm": ParameterRole.BANDWIDTH,
    "inset_depth": ParameterRole.RESISTANCE_MATCHING,
    "inset_depth_mm": ParameterRole.RESISTANCE_MATCHING,
    "inset_gap": ParameterRole.REACTANCE_MATCHING,
    "inset_gap_mm": ParameterRole.REACTANCE_MATCHING,
    "feed_x": ParameterRole.RESISTANCE_MATCHING,
    "feed_y": ParameterRole.REACTANCE_MATCHING,
}

_PIFA_ROLES: dict[str, ParameterRole] = {
    "pifa_length": ParameterRole.RESONANCE,
    "pifa_length_mm": ParameterRole.RESONANCE,
    "pifa_width": ParameterRole.BANDWIDTH,
    "pifa_width_mm": ParameterRole.BANDWIDTH,
    "pifa_height": ParameterRole.BANDWIDTH,
    "pifa_height_mm": ParameterRole.BANDWIDTH,
    "shorting_width": ParameterRole.RESISTANCE_MATCHING,
    "shorting_width_mm": ParameterRole.RESISTANCE_MATCHING,
    "feed_offset": ParameterRole.RESISTANCE_MATCHING,
    "feed_offset_mm": ParameterRole.RESISTANCE_MATCHING,
}

_IFA_ROLES: dict[str, ParameterRole] = {
    "ifa_total_length": ParameterRole.RESONANCE,
    "ifa_total_length_mm": ParameterRole.RESONANCE,
    "ifa_arm_length": ParameterRole.RESONANCE,
    "ifa_arm_length_mm": ParameterRole.RESONANCE,
    "ifa_height": ParameterRole.BANDWIDTH,
    "ifa_height_mm": ParameterRole.BANDWIDTH,
    "shorting_to_feed": ParameterRole.RESISTANCE_MATCHING,
    "shorting_to_feed_mm": ParameterRole.RESISTANCE_MATCHING,
}

_MONOPOLE_ROLES: dict[str, ParameterRole] = {
    "monopole_height": ParameterRole.RESONANCE,
    "monopole_height_mm": ParameterRole.RESONANCE,
    "wire_radius": ParameterRole.BANDWIDTH,
    "wire_radius_mm": ParameterRole.BANDWIDTH,
    "ground_radius": ParameterRole.GEOMETRY,
    "ground_radius_mm": ParameterRole.GEOMETRY,
}

_DIPOLE_ROLES: dict[str, ParameterRole] = {
    "dipole_total_length": ParameterRole.RESONANCE,
    "dipole_total_length_mm": ParameterRole.RESONANCE,
    "dipole_arm_length": ParameterRole.RESONANCE,
    "dipole_arm_length_mm": ParameterRole.RESONANCE,
    "wire_radius": ParameterRole.BANDWIDTH,
    "wire_radius_mm": ParameterRole.BANDWIDTH,
    "gap": ParameterRole.COUPLING,
    "gap_mm": ParameterRole.COUPLING,
}

_MEANDER_ROLES: dict[str, ParameterRole] = {
    "total_wire_length": ParameterRole.RESONANCE,
    "total_wire_length_mm": ParameterRole.RESONANCE,
    "segment_length": ParameterRole.GEOMETRY,
    "segment_length_mm": ParameterRole.GEOMETRY,
    "meander_height": ParameterRole.BANDWIDTH,
    "meander_height_mm": ParameterRole.BANDWIDTH,
    "trace_width": ParameterRole.RESISTANCE_MATCHING,
    "trace_width_mm": ParameterRole.RESISTANCE_MATCHING,
}

_TOPOLOGY_ROLE_MAP: dict[str, dict[str, ParameterRole]] = {
    "patch": _PATCH_ROLES,
    "pifa": _PIFA_ROLES,
    "ifa": _IFA_ROLES,
    "monopole": _MONOPOLE_ROLES,
    "dipole": _DIPOLE_ROLES,
    "meander": _MEANDER_ROLES,
}


def infer_parameter_role(
    param_name: str,
    topology: str = "",
) -> ParameterRole:
    """Infer the role of a parameter from its name and topology."""
    # Check topology-specific mapping first
    if topology:
        topo_map = _TOPOLOGY_ROLE_MAP.get(topology.lower(), {})
        role = topo_map.get(param_name)
        if role is not None:
            return role

    # Generic name-based inference
    name_lower = param_name.lower()
    if any(k in name_lower for k in ("length", "arm", "resonan")):
        return ParameterRole.RESONANCE
    if any(k in name_lower for k in ("inset", "feed", "shorting", "short_pin", "match")):
        return ParameterRole.RESISTANCE_MATCHING
    if any(k in name_lower for k in ("gap", "react", "stub")):
        return ParameterRole.REACTANCE_MATCHING
    if any(k in name_lower for k in ("width", "height", "thick", "bandwidth")):
        return ParameterRole.BANDWIDTH
    if any(k in name_lower for k in ("coupling", "spacing", "isolation")):
        return ParameterRole.COUPLING
    if "gain" in name_lower:
        return ParameterRole.GAIN
    if "eff" in name_lower:
        return ParameterRole.EFFICIENCY
    return ParameterRole.GEOMETRY


def infer_parameter_roles(
    topology: str,
    param_names: list[str],
) -> dict[str, str]:
    """Infer parameter roles for a list of parameter names as string dictionary."""
    return {name: infer_parameter_role(name, topology).value for name in param_names}


def build_parameter_metadata(
    parameters: dict[str, dict[str, Any]],
    topology: str = "",
) -> list[ParameterMeta]:
    """Build parameter metadata list from a parameters dict.

    Parameters
    ----------
    parameters:
        Dict of parameter name -> {value, min, max, step, description}.
    topology:
        Antenna topology name for role inference.
    """
    metas: list[ParameterMeta] = []
    for name, info in parameters.items():
        role = infer_parameter_role(name, topology)
        metas.append(
            ParameterMeta(
                name=name,
                role=role,
                description=info.get("description", ""),
                min_value=info.get("min"),
                max_value=info.get("max"),
                step_size=info.get("step"),
            )
        )
    return metas


def prioritize_parameters(
    metas: list[ParameterMeta],
    stage_roles: list[ParameterRole],
) -> list[ParameterMeta]:
    """Filter and sort parameters by relevance to the given stage roles."""
    relevant = [m for m in metas if m.role in stage_roles]
    # Sort by role priority within the stage
    role_order = {r: i for i, r in enumerate(stage_roles)}
    relevant.sort(key=lambda m: role_order.get(m.role, len(stage_roles)))
    return relevant
