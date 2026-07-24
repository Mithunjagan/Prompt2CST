from __future__ import annotations

import math
from dataclasses import asdict, dataclass

SPEED_OF_LIGHT_M_S = 299_792_458.0


@dataclass(frozen=True)
class CalculationResult:
    formula_id: str
    inputs: dict[str, float | str]
    output_value: float
    unit: str
    assumptions: list[str]
    warning_range: str
    source_stage: str = "deterministic_calculation"

    def to_dict(self) -> dict:
        result = asdict(self)
        result["output_value"] = round(self.output_value, 9)
        return result


def convert_units(value: float, source: str, target: str) -> CalculationResult:
    scales = {
        "m": 1.0,
        "cm": 1e-2,
        "mm": 1e-3,
        "um": 1e-6,
        "Hz": 1.0,
        "kHz": 1e3,
        "MHz": 1e6,
        "GHz": 1e9,
    }
    if source not in scales or target not in scales:
        raise ValueError("unsupported unit")
    length = source in {"m", "cm", "mm", "um"}
    if length != (target in {"m", "cm", "mm", "um"}):
        raise ValueError("cannot convert between different dimensions")
    output = value * scales[source] / scales[target]
    return _result(
        "unit_conversion", {"value": value, "source": source}, output, target
    )


def free_space_wavelength(frequency_ghz: float) -> CalculationResult:
    _positive(frequency_ghz, "frequency_ghz")
    value = SPEED_OF_LIGHT_M_S / (frequency_ghz * 1e9) * 1000
    return _result("c_over_f", {"frequency_ghz": frequency_ghz}, value, "mm")


def guided_wavelength(
    frequency_ghz: float, effective_permittivity: float
) -> CalculationResult:
    _positive(effective_permittivity, "effective_permittivity")
    value = free_space_wavelength(frequency_ghz).output_value / math.sqrt(
        effective_permittivity
    )
    return _result(
        "lambda0_over_sqrt_epsilon_eff",
        {
            "frequency_ghz": frequency_ghz,
            "effective_permittivity": effective_permittivity,
        },
        value,
        "mm",
    )


def effective_dielectric_constant(
    relative_permittivity: float, width_mm: float, height_mm: float
) -> CalculationResult:
    if relative_permittivity <= 1:
        raise ValueError("relative_permittivity must exceed 1")
    _positive(width_mm, "width_mm")
    _positive(height_mm, "height_mm")
    ratio = width_mm / height_mm
    correction = 0.04 * (1 - ratio) ** 2 if ratio < 1 else 0
    value = (
        (relative_permittivity + 1) / 2
        + (relative_permittivity - 1) / 2 * (1 + 12 / ratio) ** -0.5
        + correction
    )
    return _result(
        "hammerstad_epsilon_eff",
        {
            "relative_permittivity": relative_permittivity,
            "width_mm": width_mm,
            "height_mm": height_mm,
        },
        value,
        "dimensionless",
        ["Quasi-TEM microstrip approximation."],
        "Review for very thick substrates or dispersive materials.",
    )


def microstrip_impedance(
    width_mm: float, height_mm: float, relative_permittivity: float
) -> CalculationResult:
    epsilon_eff = effective_dielectric_constant(
        relative_permittivity, width_mm, height_mm
    ).output_value
    ratio = width_mm / height_mm
    if ratio <= 1:
        value = 60 / math.sqrt(epsilon_eff) * math.log(8 / ratio + ratio / 4)
    else:
        value = (
            120
            * math.pi
            / (
                math.sqrt(epsilon_eff)
                * (ratio + 1.393 + 0.667 * math.log(ratio + 1.444))
            )
        )
    return _result(
        "hammerstad_microstrip_impedance",
        {
            "width_mm": width_mm,
            "height_mm": height_mm,
            "relative_permittivity": relative_permittivity,
        },
        value,
        "ohm",
    )


def microstrip_width(
    impedance_ohm: float, relative_permittivity: float, height_mm: float
) -> CalculationResult:
    _positive(impedance_ohm, "impedance_ohm")
    _positive(height_mm, "height_mm")
    if relative_permittivity <= 1:
        raise ValueError("relative_permittivity must exceed 1")
    low, high = height_mm * 1e-4, height_mm * 100
    for _ in range(100):
        mid = (low + high) / 2
        current = microstrip_impedance(
            mid, height_mm, relative_permittivity
        ).output_value
        if current > impedance_ohm:
            low = mid
        else:
            high = mid
    return _result(
        "microstrip_width_bisection",
        {
            "impedance_ohm": impedance_ohm,
            "relative_permittivity": relative_permittivity,
            "height_mm": height_mm,
        },
        (low + high) / 2,
        "mm",
    )


def patch_initial_dimensions(
    frequency_ghz: float, relative_permittivity: float, height_mm: float
) -> dict[str, CalculationResult]:
    _positive(frequency_ghz, "frequency_ghz")
    if relative_permittivity <= 1:
        raise ValueError("relative_permittivity must exceed 1")
    width = (
        SPEED_OF_LIGHT_M_S
        / (2 * frequency_ghz * 1e9)
        * math.sqrt(2 / (relative_permittivity + 1))
        * 1000
    )
    epsilon_eff = effective_dielectric_constant(relative_permittivity, width, height_mm)
    ratio = width / height_mm
    delta = (
        0.412
        * height_mm
        * (
            (epsilon_eff.output_value + 0.3)
            * (ratio + 0.264)
            / ((epsilon_eff.output_value - 0.258) * (ratio + 0.8))
        )
    )
    effective_length = (
        guided_wavelength(frequency_ghz, epsilon_eff.output_value).output_value / 2
    )
    length = effective_length - 2 * delta
    return {
        "width": _result(
            "patch_width_initial",
            {
                "frequency_ghz": frequency_ghz,
                "relative_permittivity": relative_permittivity,
            },
            width,
            "mm",
        ),
        "length": _result(
            "patch_length_fringing_corrected",
            {"effective_length_mm": effective_length, "delta_length_mm": delta},
            length,
            "mm",
        ),
        "effective_permittivity": epsilon_eff,
        "fringing_extension": _result(
            "hammerstad_delta_length", {"width_height_ratio": ratio}, delta, "mm"
        ),
    }


def monopole_initial_length(
    frequency_ghz: float, shortening_factor: float = 0.95
) -> CalculationResult:
    if not 0.5 <= shortening_factor <= 1:
        raise ValueError("shortening_factor must be between 0.5 and 1")
    value = free_space_wavelength(frequency_ghz).output_value / 4 * shortening_factor
    return _result(
        "quarter_wave_monopole",
        {"frequency_ghz": frequency_ghz, "shortening_factor": shortening_factor},
        value,
        "mm",
    )


def dipole_initial_length(
    frequency_ghz: float, shortening_factor: float = 0.95
) -> CalculationResult:
    if not 0.5 <= shortening_factor <= 1:
        raise ValueError("shortening_factor must be between 0.5 and 1")
    value = free_space_wavelength(frequency_ghz).output_value / 2 * shortening_factor
    return _result(
        "half_wave_dipole",
        {"frequency_ghz": frequency_ghz, "shortening_factor": shortening_factor},
        value,
        "mm",
    )


def quarter_wave(
    frequency_ghz: float, effective_permittivity: float = 1
) -> CalculationResult:
    value = guided_wavelength(frequency_ghz, effective_permittivity).output_value / 4
    return _result(
        "quarter_guided_wavelength",
        {
            "frequency_ghz": frequency_ghz,
            "effective_permittivity": effective_permittivity,
        },
        value,
        "mm",
    )


def half_wave(
    frequency_ghz: float, effective_permittivity: float = 1
) -> CalculationResult:
    value = guided_wavelength(frequency_ghz, effective_permittivity).output_value / 2
    return _result(
        "half_guided_wavelength",
        {
            "frequency_ghz": frequency_ghz,
            "effective_permittivity": effective_permittivity,
        },
        value,
        "mm",
    )


def substrate_length_correction(
    height_mm: float, effective_permittivity: float, width_mm: float
) -> CalculationResult:
    _positive(height_mm, "height_mm")
    _positive(width_mm, "width_mm")
    if effective_permittivity <= 0.258:
        raise ValueError("effective_permittivity must exceed 0.258")
    ratio = width_mm / height_mm
    value = (
        0.412
        * height_mm
        * (
            (effective_permittivity + 0.3)
            * (ratio + 0.264)
            / ((effective_permittivity - 0.258) * (ratio + 0.8))
        )
    )
    return _result(
        "substrate_fringing_correction",
        {
            "height_mm": height_mm,
            "effective_permittivity": effective_permittivity,
            "width_mm": width_mm,
        },
        value,
        "mm",
    )


def airbox_recommendation(
    frequency_min_ghz: float, fraction: float = 0.25
) -> CalculationResult:
    if not 0.1 <= fraction <= 1:
        raise ValueError("fraction must be between 0.1 and 1")
    value = free_space_wavelength(frequency_min_ghz).output_value * fraction
    return _result(
        "airbox_lambda_fraction",
        {"frequency_min_ghz": frequency_min_ghz, "fraction": fraction},
        value,
        "mm",
    )


def mesh_resolution_recommendation(
    frequency_max_ghz: float,
    relative_permittivity_max: float = 1,
    lines_per_wavelength: int = 20,
) -> CalculationResult:
    if not 4 <= lines_per_wavelength <= 100:
        raise ValueError("lines_per_wavelength must be between 4 and 100")
    value = (
        guided_wavelength(frequency_max_ghz, relative_permittivity_max).output_value
        / lines_per_wavelength
    )
    return _result(
        "mesh_guided_wavelength_fraction",
        {
            "frequency_max_ghz": frequency_max_ghz,
            "relative_permittivity_max": relative_permittivity_max,
            "lines_per_wavelength": lines_per_wavelength,
        },
        value,
        "mm",
    )


def _positive(value: float, name: str) -> None:
    if value <= 0 or not math.isfinite(value):
        raise ValueError(f"{name} must be positive and finite")


def _result(
    formula_id: str,
    inputs: dict[str, float | str],
    value: float,
    unit: str,
    assumptions: list[str] | None = None,
    warning_range: str = "Validate against the intended material and frequency range.",
) -> CalculationResult:
    return CalculationResult(
        formula_id=formula_id,
        inputs=inputs,
        output_value=value,
        unit=unit,
        assumptions=assumptions or ["Deterministic closed-form engineering estimate."],
        warning_range=warning_range,
    )
