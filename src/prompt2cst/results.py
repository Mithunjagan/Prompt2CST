from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ResultProvenance(StrEnum):
    EXTRACTED_CST = "extracted_cst"
    DERIVED_FROM_CST = "derived_from_cst"
    CALCULATED = "calculated"
    MODEL_INFERENCE = "model_inference"
    RECOMMENDATION = "recommendation"
    MOCK_SIMULATION = "mock_simulation"
    CST_SIMULATION = "cst_simulation"
    CLOSED_FORM = "closed_form"


class ResultValue(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    value: float | list[float] | list[dict[str, float]]
    unit: str
    provenance: ResultProvenance


class SimulationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: str = "1.0"
    execution_id: str
    status: str
    values: list[ResultValue] = Field(default_factory=list)
    missing_requested_outputs: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    raw_metadata: dict[str, Any] = Field(default_factory=dict)

    def get_value(self, name: str) -> Any | None:
        for val in self.values:
            if val.name == name:
                return val.value
        return None

    def get_s11_db(self) -> float | None:
        val = self.get_value("s11_db") or self.get_value("s11")
        if isinstance(val, (int, float)):
            return float(val)
        return None

    def get_impedance(self) -> tuple[float, float] | None:
        re = self.get_value("zin_re") or self.get_value("re_z")
        im = self.get_value("zin_im") or self.get_value("im_z")
        if re is not None and im is not None:
            return (float(re), float(im))
        return None


def normalize_simulation_results(
    execution_id: str,
    extracted: dict[str, tuple[Any, str]],
    requested_outputs: list[str],
    raw_metadata: dict[str, Any] | None = None,
    derived_outputs: set[str] | None = None,
) -> SimulationResult:
    derived_outputs = derived_outputs or set()
    values = [
        ResultValue(
            name=name,
            value=value,
            unit=unit,
            provenance=(
                ResultProvenance.DERIVED_FROM_CST
                if name in derived_outputs
                else ResultProvenance.EXTRACTED_CST
            ),
        )
        for name, (value, unit) in sorted(extracted.items())
    ]
    missing = sorted(set(requested_outputs) - set(extracted))
    return SimulationResult(
        execution_id=execution_id,
        status="partial" if missing else "complete",
        values=values,
        missing_requested_outputs=missing,
        warnings=["Missing outputs were not inferred."] if missing else [],
        raw_metadata=raw_metadata or {},
    )
