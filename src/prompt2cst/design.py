from __future__ import annotations

import math
from dataclasses import asdict, dataclass

SPEED_OF_LIGHT_M_S = 299_792_458.0


@dataclass(frozen=True)
class PatchInputs:
    frequency_ghz: float = 2.45
    relative_permittivity: float = 4.3
    substrate_height_mm: float = 1.6
    loss_tangent: float = 0.02
    conductor_thickness_mm: float = 0.035
    feed_impedance_ohm: float = 50.0
    estimated_edge_resistance_ohm: float = 300.0
    inset_gap_mm: float = 0.5

    def validate(self) -> None:
        if not 0.1 <= self.frequency_ghz <= 100.0:
            raise ValueError("frequency_ghz must be between 0.1 and 100")
        if not 1.0 < self.relative_permittivity <= 20.0:
            raise ValueError(
                "relative_permittivity must be greater than 1 and at most 20"
            )
        if not 0.05 <= self.substrate_height_mm <= 10.0:
            raise ValueError("substrate_height_mm must be between 0.05 and 10")
        if not 0.0 <= self.loss_tangent <= 0.2:
            raise ValueError("loss_tangent must be between 0 and 0.2")
        if not 0.001 <= self.conductor_thickness_mm <= 1.0:
            raise ValueError("conductor_thickness_mm must be between 0.001 and 1")
        if not 10.0 <= self.feed_impedance_ohm <= 200.0:
            raise ValueError("feed_impedance_ohm must be between 10 and 200")
        if self.estimated_edge_resistance_ohm <= self.feed_impedance_ohm:
            raise ValueError(
                "estimated_edge_resistance_ohm must exceed feed_impedance_ohm"
            )
        if not 0.05 <= self.inset_gap_mm <= 5.0:
            raise ValueError("inset_gap_mm must be between 0.05 and 5")


@dataclass(frozen=True)
class PatchDesign:
    inputs: PatchInputs
    patch_width_mm: float
    patch_length_mm: float
    effective_permittivity: float
    fringing_extension_mm: float
    ground_width_mm: float
    ground_length_mm: float
    feed_width_mm: float
    inset_depth_mm: float
    inset_opening_mm: float
    sweep_start_ghz: float
    sweep_stop_ghz: float

    def to_dict(self) -> dict:
        result = asdict(self)
        return _round_floats(result)


def calculate_rectangular_patch(inputs: PatchInputs) -> PatchDesign:
    """Calculate a first-pass inset-fed rectangular microstrip patch."""

    inputs.validate()

    frequency_hz = inputs.frequency_ghz * 1e9
    height_m = inputs.substrate_height_mm / 1000.0
    epsilon_r = inputs.relative_permittivity

    patch_width_m = (
        SPEED_OF_LIGHT_M_S / (2.0 * frequency_hz) * math.sqrt(2.0 / (epsilon_r + 1.0))
    )

    width_height_ratio = patch_width_m / height_m
    epsilon_eff = (epsilon_r + 1.0) / 2.0 + (epsilon_r - 1.0) / 2.0 * (
        1.0 + 12.0 / width_height_ratio
    ) ** -0.5

    delta_length_m = (
        0.412
        * height_m
        * (
            (epsilon_eff + 0.3)
            * (width_height_ratio + 0.264)
            / ((epsilon_eff - 0.258) * (width_height_ratio + 0.8))
        )
    )

    effective_length_m = SPEED_OF_LIGHT_M_S / (
        2.0 * frequency_hz * math.sqrt(epsilon_eff)
    )
    patch_length_m = effective_length_m - 2.0 * delta_length_m

    feed_width_m = _microstrip_width_m(
        impedance_ohm=inputs.feed_impedance_ohm,
        epsilon_r=epsilon_r,
        height_m=height_m,
    )

    resistance_ratio = inputs.feed_impedance_ohm / inputs.estimated_edge_resistance_ohm
    inset_depth_m = patch_length_m / math.pi * math.acos(math.sqrt(resistance_ratio))
    inset_depth_m = min(inset_depth_m, patch_length_m * 0.45)

    patch_width_mm = patch_width_m * 1000.0
    patch_length_mm = patch_length_m * 1000.0
    feed_width_mm = feed_width_m * 1000.0

    return PatchDesign(
        inputs=inputs,
        patch_width_mm=patch_width_mm,
        patch_length_mm=patch_length_mm,
        effective_permittivity=epsilon_eff,
        fringing_extension_mm=delta_length_m * 1000.0,
        ground_width_mm=patch_width_mm + 6.0 * inputs.substrate_height_mm,
        ground_length_mm=patch_length_mm + 6.0 * inputs.substrate_height_mm,
        feed_width_mm=feed_width_mm,
        inset_depth_mm=inset_depth_m * 1000.0,
        inset_opening_mm=feed_width_mm + 2.0 * inputs.inset_gap_mm,
        sweep_start_ghz=max(0.01, inputs.frequency_ghz * 0.75),
        sweep_stop_ghz=inputs.frequency_ghz * 1.25,
    )


@dataclass(frozen=True)
class MonopoleInputs:
    frequency_ghz: float = 2.45
    wire_length_mm: float = 30.6
    wire_radius_mm: float = 0.612
    ground_size_mm: float = 61.2
    ground_thickness_mm: float = 0.5
    feed_gap_mm: float = 1.5
    port_impedance_ohm: float = 50.0
    sweep_start_ghz: float = 2.0
    sweep_stop_ghz: float = 3.0

    def validate(self) -> None:
        if not 0.1 <= self.frequency_ghz <= 100.0:
            raise ValueError("frequency_ghz must be between 0.1 and 100")
        if not 0.1 <= self.wire_length_mm <= 1000.0:
            raise ValueError("wire_length_mm must be between 0.1 and 1000")
        if not 0.01 <= self.wire_radius_mm <= 100.0:
            raise ValueError("wire_radius_mm must be between 0.01 and 100")
        if self.wire_radius_mm * 2.0 >= self.ground_size_mm:
            raise ValueError("wire diameter must be smaller than ground_size_mm")
        if not 1.0 <= self.ground_size_mm <= 5000.0:
            raise ValueError("ground_size_mm must be between 1 and 5000")
        if not 0.01 <= self.ground_thickness_mm <= 20.0:
            raise ValueError("ground_thickness_mm must be between 0.01 and 20")
        if not 0.01 <= self.feed_gap_mm <= 50.0:
            raise ValueError("feed_gap_mm must be between 0.01 and 50")
        if not 10.0 <= self.port_impedance_ohm <= 200.0:
            raise ValueError("port_impedance_ohm must be between 10 and 200")
        if not 0.01 <= self.sweep_start_ghz < self.sweep_stop_ghz <= 100.0:
            raise ValueError("frequency sweep must satisfy 0.01 <= start < stop <= 100")
        if not self.sweep_start_ghz <= self.frequency_ghz <= self.sweep_stop_ghz:
            raise ValueError("frequency_ghz must lie inside the simulation sweep")


@dataclass(frozen=True)
class MonopoleDesign:
    inputs: MonopoleInputs
    ground_xmin_mm: float
    ground_xmax_mm: float
    ground_ymin_mm: float
    ground_ymax_mm: float
    ground_zmin_mm: float
    ground_zmax_mm: float
    monopole_zmin_mm: float
    monopole_zmax_mm: float
    free_space_wavelength_mm: float
    quarter_wavelength_mm: float

    @property
    def sweep_start_ghz(self) -> float:
        return self.inputs.sweep_start_ghz

    @property
    def sweep_stop_ghz(self) -> float:
        return self.inputs.sweep_stop_ghz

    def to_dict(self) -> dict:
        return _round_floats(asdict(self))


def calculate_wire_monopole(inputs: MonopoleInputs) -> MonopoleDesign:
    """Validate and place a vertical cylindrical monopole above a PEC ground."""

    inputs.validate()
    half_ground = inputs.ground_size_mm / 2.0
    wavelength_mm = SPEED_OF_LIGHT_M_S / (inputs.frequency_ghz * 1e9) * 1000.0

    return MonopoleDesign(
        inputs=inputs,
        ground_xmin_mm=-half_ground,
        ground_xmax_mm=half_ground,
        ground_ymin_mm=-half_ground,
        ground_ymax_mm=half_ground,
        ground_zmin_mm=-inputs.ground_thickness_mm,
        ground_zmax_mm=0.0,
        monopole_zmin_mm=inputs.feed_gap_mm,
        monopole_zmax_mm=inputs.feed_gap_mm + inputs.wire_length_mm,
        free_space_wavelength_mm=wavelength_mm,
        quarter_wavelength_mm=wavelength_mm / 4.0,
    )


@dataclass(frozen=True)
class DipoleInputs:
    frequency_ghz: float = 2.45
    total_conductor_length_mm: float = 61.2
    wire_radius_mm: float = 0.5
    feed_gap_mm: float = 1.5
    port_impedance_ohm: float = 50.0
    sweep_start_ghz: float = 2.0
    sweep_stop_ghz: float = 3.0

    def validate(self) -> None:
        if not 0.1 <= self.frequency_ghz <= 100.0:
            raise ValueError("frequency_ghz must be between 0.1 and 100")
        if not 0.2 <= self.total_conductor_length_mm <= 2000.0:
            raise ValueError("total_conductor_length_mm must be between 0.2 and 2000")
        if not 0.01 <= self.wire_radius_mm <= 100.0:
            raise ValueError("wire_radius_mm must be between 0.01 and 100")
        if not 0.01 <= self.feed_gap_mm <= 100.0:
            raise ValueError("feed_gap_mm must be between 0.01 and 100")
        if not 10.0 <= self.port_impedance_ohm <= 200.0:
            raise ValueError("port_impedance_ohm must be between 10 and 200")
        if not 0.01 <= self.sweep_start_ghz < self.sweep_stop_ghz <= 100.0:
            raise ValueError("frequency sweep must satisfy 0.01 <= start < stop <= 100")
        if not self.sweep_start_ghz <= self.frequency_ghz <= self.sweep_stop_ghz:
            raise ValueError("frequency_ghz must lie inside the simulation sweep")


@dataclass(frozen=True)
class DipoleDesign:
    inputs: DipoleInputs
    lower_zmin_mm: float
    lower_zmax_mm: float
    upper_zmin_mm: float
    upper_zmax_mm: float
    free_space_wavelength_mm: float
    half_wavelength_mm: float

    @property
    def sweep_start_ghz(self) -> float:
        return self.inputs.sweep_start_ghz

    @property
    def sweep_stop_ghz(self) -> float:
        return self.inputs.sweep_stop_ghz

    def to_dict(self) -> dict:
        return _round_floats(asdict(self))


def calculate_center_fed_dipole(inputs: DipoleInputs) -> DipoleDesign:
    """Place two equal cylindrical arms around a center feed gap."""

    inputs.validate()
    arm_length = inputs.total_conductor_length_mm / 2.0
    half_gap = inputs.feed_gap_mm / 2.0
    wavelength_mm = SPEED_OF_LIGHT_M_S / (inputs.frequency_ghz * 1e9) * 1000.0
    return DipoleDesign(
        inputs=inputs,
        lower_zmin_mm=-half_gap - arm_length,
        lower_zmax_mm=-half_gap,
        upper_zmin_mm=half_gap,
        upper_zmax_mm=half_gap + arm_length,
        free_space_wavelength_mm=wavelength_mm,
        half_wavelength_mm=wavelength_mm / 2.0,
    )


def _microstrip_width_m(
    impedance_ohm: float,
    epsilon_r: float,
    height_m: float,
) -> float:
    """Hammerstad-style closed-form estimate of microstrip width."""

    a_value = impedance_ohm / 60.0 * math.sqrt((epsilon_r + 1.0) / 2.0) + (
        epsilon_r - 1.0
    ) / (epsilon_r + 1.0) * (0.23 + 0.11 / epsilon_r)
    width_height_ratio = 8.0 * math.exp(a_value) / (math.exp(2.0 * a_value) - 2.0)

    if width_height_ratio >= 2.0:
        b_value = 377.0 * math.pi / (2.0 * impedance_ohm * math.sqrt(epsilon_r))
        width_height_ratio = (
            2.0
            / math.pi
            * (
                b_value
                - 1.0
                - math.log(2.0 * b_value - 1.0)
                + (epsilon_r - 1.0)
                / (2.0 * epsilon_r)
                * (math.log(b_value - 1.0) + 0.39 - 0.61 / epsilon_r)
            )
        )

    return width_height_ratio * height_m


def _round_floats(value):
    if isinstance(value, float):
        return round(value, 6)
    if isinstance(value, dict):
        return {key: _round_floats(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_round_floats(item) for item in value]
    return value
