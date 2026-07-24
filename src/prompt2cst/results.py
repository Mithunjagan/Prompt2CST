from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ResultProvenance(StrEnum):
    EXTRACTED_CST = "extracted_cst"
    CALCULATED = "calculated"
    MODEL_INFERENCE = "model_inference"
    RECOMMENDATION = "recommendation"


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


def normalize_simulation_results(
    execution_id: str,
    extracted: dict[str, tuple[Any, str]],
    requested_outputs: list[str],
) -> SimulationResult:
    values = [
        ResultValue(
            name=name,
            value=value,
            unit=unit,
            provenance=ResultProvenance.EXTRACTED_CST,
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
    )
