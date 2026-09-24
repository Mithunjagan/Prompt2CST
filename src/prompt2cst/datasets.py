"""Safe ingestion and analysis of parameterized S11 sweep datasets.

Faculty or laboratory datasets are useful evidence, but they are not a
substitute for geometry semantics or solver validation.  This module keeps
that boundary explicit while making the numerical evidence available to the
local autonomous workflow.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from zipfile import BadZipFile, ZipFile


MAX_DATASET_FILES = 10_000
MAX_ENTRY_BYTES = 10 * 1024 * 1024
MAX_TOTAL_BYTES = 100 * 1024 * 1024
_PARAMETER_RE = re.compile(r"([A-Za-z][A-Za-z0-9_]*)=([-+0-9.eE]+)")


@dataclass(frozen=True)
class S11Sample:
    frequency_ghz: float
    magnitude_db: float

    def to_dict(self) -> dict[str, float]:
        return {"frequency_ghz": self.frequency_ghz, "magnitude_db": self.magnitude_db}


@dataclass(frozen=True)
class SweepDesign:
    source_entry: str
    sha256: str
    parameters: dict[str, float]
    samples: tuple[S11Sample, ...]

    @property
    def resonance(self) -> S11Sample:
        return min(self.samples, key=lambda sample: sample.magnitude_db)

    def sample_near(self, frequency_ghz: float) -> S11Sample:
        return min(self.samples, key=lambda sample: abs(sample.frequency_ghz - frequency_ghz))

    def to_dict(self, *, include_samples: bool = False) -> dict[str, Any]:
        resonance = self.resonance
        result: dict[str, Any] = {
            "source_entry": self.source_entry,
            "sha256": self.sha256,
            "parameters": dict(sorted(self.parameters.items())),
            "sample_count": len(self.samples),
            "frequency_min_ghz": self.samples[0].frequency_ghz,
            "frequency_max_ghz": self.samples[-1].frequency_ghz,
            "resonance_ghz": resonance.frequency_ghz,
            "minimum_s11_db": resonance.magnitude_db,
            "samples_at_or_below_minus_10_db": sum(
                sample.magnitude_db <= -10.0 for sample in self.samples
            ),
        }
        if include_samples:
            result["samples"] = [sample.to_dict() for sample in self.samples]
        return result


@dataclass(frozen=True)
class FacultyDataset:
    archive_path: Path
    archive_sha256: str
    designs: tuple[SweepDesign, ...]

    @classmethod
    def load(cls, archive_path: str | Path) -> "FacultyDataset":
        path = Path(archive_path).resolve()
        if not path.is_file():
            raise FileNotFoundError(f"Dataset archive not found: {path}")
        archive_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        designs: list[SweepDesign] = []
        total_size = 0
        try:
            with ZipFile(path) as archive:
                entries = [entry for entry in archive.infolist() if not entry.is_dir()]
                if len(entries) > MAX_DATASET_FILES:
                    raise ValueError(f"Dataset has too many files ({len(entries)}).")
                for entry in entries:
                    normalized = entry.filename.replace("\\", "/")
                    if normalized.startswith("/") or ".." in normalized.split("/"):
                        raise ValueError(f"Unsafe dataset entry path: {entry.filename}")
                    if not normalized.lower().endswith(".txt"):
                        raise ValueError(f"Unsupported dataset entry type: {entry.filename}")
                    if entry.file_size > MAX_ENTRY_BYTES:
                        raise ValueError(f"Dataset entry is too large: {entry.filename}")
                    total_size += entry.file_size
                    if total_size > MAX_TOTAL_BYTES:
                        raise ValueError("Dataset exceeds the uncompressed size limit.")
                    payload = archive.read(entry)
                    designs.append(_parse_sweep(normalized, payload))
        except BadZipFile as exc:
            raise ValueError(f"Invalid dataset ZIP archive: {path}") from exc
        if not designs:
            raise ValueError("Dataset archive contains no sweep files.")
        return cls(path, archive_hash, tuple(designs))

    def analyze(self, target_frequency_ghz: float | None = None) -> dict[str, Any]:
        parameter_names = sorted({name for design in self.designs for name in design.parameters})
        parameter_values = {
            name: sorted({design.parameters[name] for design in self.designs if name in design.parameters})
            for name in parameter_names
        }
        fixed = {name: values[0] for name, values in parameter_values.items() if len(values) == 1}
        varying = {name: values for name, values in parameter_values.items() if len(values) > 1}
        resonances = [design.resonance for design in self.designs]
        ranked: list[dict[str, Any]] = []
        target_assessment: dict[str, Any] | None = None
        if target_frequency_ghz is not None:
            if not math.isfinite(target_frequency_ghz) or target_frequency_ghz <= 0:
                raise ValueError("target_frequency_ghz must be a positive finite number")
            for design in self.designs:
                target_sample = design.sample_near(target_frequency_ghz)
                resonance = design.resonance
                ranked.append({
                    "source_entry": design.source_entry,
                    "parameters": dict(sorted(design.parameters.items())),
                    "sample_frequency_ghz": target_sample.frequency_ghz,
                    "s11_at_target_db": target_sample.magnitude_db,
                    "resonance_ghz": resonance.frequency_ghz,
                    "minimum_s11_db": resonance.magnitude_db,
                    "resonance_error_ghz": abs(resonance.frequency_ghz - target_frequency_ghz),
                })
            ranked.sort(key=lambda row: (row["s11_at_target_db"], row["resonance_error_ghz"]))
            passing = [row for row in ranked if row["s11_at_target_db"] <= -10.0]
            best = ranked[0]
            target_assessment = {
                "status": "SUPPORTED_BY_DATASET" if passing else "NO_MATCH_AT_TARGET",
                "designs_meeting_minus_10_db": len(passing),
                "best_source_entry": best["source_entry"],
                "best_s11_at_target_db": best["s11_at_target_db"],
                "sample_frequency_ghz": best["sample_frequency_ghz"],
                "use_as_optimizer_seed": bool(passing),
                "reason": (
                    "At least one supplied design reaches -10 dB at the requested frequency."
                    if passing
                    else "No supplied design reaches -10 dB at the requested frequency; do not treat this dataset as a validated seed."
                ),
            }
        baseline = {
            name: Counter(
                design.parameters[name] for design in self.designs if name in design.parameters
            ).most_common(1)[0][0]
            for name in parameter_names
        }
        one_factor = self._one_factor_analysis(baseline, varying, target_frequency_ghz)
        return {
            "schema_version": "1.0",
            "kind": "parameterized_s11_sweep_dataset",
            "archive_path": str(self.archive_path),
            "archive_sha256": self.archive_sha256,
            "design_count": len(self.designs),
            "sample_count": sum(len(design.samples) for design in self.designs),
            "frequency_range_ghz": [
                min(design.samples[0].frequency_ghz for design in self.designs),
                max(design.samples[-1].frequency_ghz for design in self.designs),
            ],
            "parameter_values": parameter_values,
            "fixed_parameters": fixed,
            "varying_parameters": varying,
            "minimum_s11_db_range": [
                min(sample.magnitude_db for sample in resonances),
                max(sample.magnitude_db for sample in resonances),
            ],
            "designs_reaching_minus_10_db": sum(
                design.resonance.magnitude_db <= -10.0 for design in self.designs
            ),
            "target_frequency_ghz": target_frequency_ghz,
            "target_assessment": target_assessment,
            "target_ranking": ranked,
            "baseline_parameters": baseline,
            "one_factor_sensitivity": one_factor,
            "provenance": "USER_SUPPLIED_FACULTY_DATASET",
            "allowed_uses": [
                "parameter sensitivity analysis",
                "candidate ranking within this dataset",
                "surrogate-model training with held-out validation",
                "optimizer regression testing",
            ],
            "manufacturing_use": "BLOCKED_MISSING_GEOMETRY_PARAMETER_MAP",
            "limitations": [
                "Opaque parameter names are not assumed to represent any specific geometry.",
                "S11 magnitude alone does not establish impedance, gain, efficiency, radiation pattern, or manufacturability.",
                "Dataset predictions require fresh solver or measurement validation before design acceptance.",
            ],
        }

    def _one_factor_analysis(
        self,
        baseline: dict[str, float],
        varying: dict[str, list[float]],
        target_frequency_ghz: float | None,
    ) -> dict[str, Any]:
        analysis: dict[str, Any] = {}
        for active_name in varying:
            records: list[dict[str, Any]] = []
            for design in self.designs:
                if any(
                    name != active_name
                    and name in design.parameters
                    and not math.isclose(design.parameters[name], value, abs_tol=1e-12)
                    for name, value in baseline.items()
                ):
                    continue
                resonance = design.resonance
                row: dict[str, Any] = {
                    "value": design.parameters[active_name],
                    "resonance_ghz": resonance.frequency_ghz,
                    "minimum_s11_db": resonance.magnitude_db,
                    "source_entry": design.source_entry,
                }
                if target_frequency_ghz is not None:
                    target_sample = design.sample_near(target_frequency_ghz)
                    row["s11_at_target_db"] = target_sample.magnitude_db
                    row["sample_frequency_ghz"] = target_sample.frequency_ghz
                records.append(row)
            unique = {record["value"]: record for record in records}
            ordered = [unique[value] for value in sorted(unique)]
            if len(ordered) < 2:
                continue
            low, high = ordered[0], ordered[-1]
            span = high["value"] - low["value"]
            analysis[active_name] = {
                "method": "one_factor_at_a_time_around_modal_baseline",
                "sample_count": len(ordered),
                "records": ordered,
                "resonance_slope_ghz_per_unit": (
                    (high["resonance_ghz"] - low["resonance_ghz"]) / span
                    if span else None
                ),
                "minimum_s11_change_db": high["minimum_s11_db"] - low["minimum_s11_db"],
            }
        return analysis

    def save_study(self, output_dir: str | Path, target_frequency_ghz: float | None = None) -> dict[str, str]:
        root = Path(output_dir).resolve()
        root.mkdir(parents=True, exist_ok=True)
        summary = self.analyze(target_frequency_ghz)
        records = {
            "schema_version": "1.0",
            "archive_sha256": self.archive_sha256,
            "designs": [design.to_dict(include_samples=True) for design in self.designs],
        }
        summary_path = _atomic_json(root / "dataset_summary.json", summary)
        records_path = _atomic_json(root / "normalized_sweeps.json", records)
        return {"summary": str(summary_path), "normalized_sweeps": str(records_path)}


def _parse_sweep(source_entry: str, payload: bytes) -> SweepDesign:
    if b"\x00" in payload:
        raise ValueError(f"Dataset entry is not plain text: {source_entry}")
    text = payload.decode("utf-8-sig", errors="strict")
    lines = text.splitlines()
    if not lines or not lines[0].startswith("#Parameters"):
        raise ValueError(f"Dataset entry has no parameter header: {source_entry}")
    parameters: dict[str, float] = {}
    for match in _PARAMETER_RE.finditer(lines[0]):
        name, raw = match.groups()
        value = float(raw)
        if not math.isfinite(value):
            raise ValueError(f"Non-finite parameter {name} in {source_entry}")
        parameters[name] = value
    if not parameters:
        raise ValueError(f"Dataset entry has no valid parameters: {source_entry}")
    samples: list[S11Sample] = []
    for line in lines[1:]:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        fields = stripped.split()
        if len(fields) != 2:
            raise ValueError(f"Malformed S11 row in {source_entry}: {stripped[:80]}")
        frequency, magnitude = (float(field) for field in fields)
        if not math.isfinite(frequency) or not math.isfinite(magnitude):
            raise ValueError(f"Non-finite S11 row in {source_entry}")
        if samples and frequency <= samples[-1].frequency_ghz:
            raise ValueError(f"Frequencies must increase in {source_entry}")
        samples.append(S11Sample(frequency, magnitude))
    if len(samples) < 2:
        raise ValueError(f"Dataset entry has too few S11 samples: {source_entry}")
    return SweepDesign(source_entry, hashlib.sha256(payload).hexdigest(), parameters, tuple(samples))


def _atomic_json(path: Path, value: Any) -> Path:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True), encoding="utf-8")
    temporary.replace(path)
    return path
