"""Local-first, artifact-backed autonomous design workflow.

This module deliberately separates a design *proposal* from electromagnetic
truth.  ``mock`` runs deterministic synthetic physics and labels every result;
``cst`` delegates only to :class:`RealCSTRunner`; ``dry-run`` writes no RF
results at all.  Each stage persists an immutable workspace artifact so a
stopped job can be inspected and resumed without treating prior assumptions as
measurements.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .architect import AntennaTopology, RFArchitectureAgent
from .cost_guard import CostGuard
from .evidence import EvidenceDatabase, SearchCoverage
from .optimizer.checkpoint import CheckpointData, CheckpointManager
from .optimizer.pipeline import OptimizationPipeline, OptimizationPipelineConfig
from .optimizer.runner import MockCSTRunner, RealCSTRunner
from .optimizer.schema import FrequencyRange, OptimizationGoalConfig, ParameterBound
from .orchestrator import ChiefOrchestrator
from .papers import PaperIngestionEngine
from .shared_state import ArtifactType, ProjectWorkspace, TaskState
from .wearable import WearableAntennaEvaluator


_SUPPORTED_CST_TOPOLOGIES = {"patch", "monopole", "dipole"}
_FREQ_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:-|–|to)\s*(\d+(?:\.\d+)?)\s*ghz|(?<![\d.])(\d+(?:\.\d+)?)\s*ghz", re.I)
_S11_RE = re.compile(r"s\s*11\s*(?:<|≤|less than)?\s*[−-]?\s*(\d+(?:\.\d+)?)\s*db", re.I)


@dataclass(frozen=True)
class DesignRun:
    project_dir: Path
    status: str
    mode: str
    selected_topology: str
    artifacts: dict[str, str]
    simulation_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_dir": str(self.project_dir), "status": self.status,
            "mode": self.mode, "selected_topology": self.selected_topology,
            "artifacts": self.artifacts, "simulation_count": self.simulation_count,
        }


def load_spec(path: str | Path) -> dict[str, Any]:
    """Load a local YAML/JSON design specification without executing tags."""
    spec_path = Path(path)
    if not spec_path.is_file():
        raise FileNotFoundError(f"Design specification not found: {spec_path}")
    with spec_path.open("r", encoding="utf-8") as handle:
        if spec_path.suffix.lower() == ".json":
            parsed = json.load(handle)
        else:
            parsed = yaml.safe_load(handle)
    if not isinstance(parsed, dict):
        raise ValueError("Design specification must contain a mapping at its root.")
    return parsed


def extract_requirements(prompt: str, spec: dict[str, Any] | None = None) -> dict[str, Any]:
    """Conservatively extract only requirements explicitly present in input."""
    spec = spec or {}
    req = spec.get("requirements", {}) if isinstance(spec.get("requirements"), dict) else {}
    frequency = req.get("frequency", {}) if isinstance(req.get("frequency"), dict) else {}
    text = prompt.lower()
    match = _FREQ_RE.search(prompt)
    if match and match.group(1):
        min_ghz, max_ghz = float(match.group(1)), float(match.group(2))
    elif match:
        center = float(match.group(3))
        min_ghz, max_ghz = center * 0.95, center * 1.05
    else:
        center_hz = _as_float(frequency.get("center_hz"), 2.45e9)
        min_ghz = _as_float(frequency.get("min_hz"), center_hz * 0.95) / 1e9
        max_ghz = _as_float(frequency.get("max_hz"), center_hz * 1.05) / 1e9
    if "min_hz" in frequency:
        min_ghz = _as_float(frequency["min_hz"], min_ghz * 1e9) / 1e9
    if "max_hz" in frequency:
        max_ghz = _as_float(frequency["max_hz"], max_ghz * 1e9) / 1e9
    center_ghz = _as_float(frequency.get("center_hz"), (min_ghz + max_ghz) * 0.5e9) / 1e9
    s11_match = _S11_RE.search(prompt)
    s11_cfg = req.get("s11", {}) if isinstance(req.get("s11"), dict) else {}
    impedance_cfg = req.get("impedance", {}) if isinstance(req.get("impedance"), dict) else {}
    application = spec.get("application", {}) if isinstance(spec.get("application"), dict) else {}
    wearable = any(word in text for word in ("wearable", "smart glasses", "eyewear", "head loading", "head-loading")) or application.get("type") == "wearable"
    return {
        "prompt": prompt,
        "application": application.get("device") or ("smart_glasses" if "glasses" in text else None),
        "location": application.get("form_factor") or ("temple" if "temple" in text else None),
        "frequency_min_ghz": min_ghz,
        "frequency_max_ghz": max_ghz,
        "center_frequency_hz": center_ghz * 1e9,
        "target_impedance_ohm": _as_float(impedance_cfg.get("target_re_ohm"), 50.0),
        "target_s11_db": -abs(float(s11_match.group(1))) if s11_match else _as_float(s11_cfg.get("target_db"), -10.0),
        "wearable": wearable,
        "head_loading": wearable or bool(application.get("tissue_loading")),
        "candidate_topologies": spec.get("candidate_topologies", []),
        "assumptions": [
            "No fabrication, measurement, or regulatory certification is implied.",
            "Closed-form dimensions are INITIAL_ESTIMATE values until CST or measurement verifies them.",
        ],
    }


def run_design(
    prompt: str,
    project_dir: str | Path,
    *,
    mode: str = "dry-run",
    papers: list[str | Path] | None = None,
    spec: dict[str, Any] | None = None,
    cst_project_path: str | None = None,
    max_iterations: int = 15,
) -> DesignRun:
    """Execute a local-first design run and write all audit artifacts."""
    if mode not in {"dry-run", "mock", "cst"}:
        raise ValueError("mode must be dry-run, mock, or cst")
    if mode == "cst" and not cst_project_path:
        raise ValueError("--mode cst requires --project-path to a parameterized CST project")

    root = Path(project_dir).resolve()
    workspace = ProjectWorkspace(root)
    chief = ChiefOrchestrator(workspace=workspace, cost_guard=CostGuard())
    requirements = extract_requirements(prompt, spec)
    chief.initialize_project(
        goal=prompt, frequency_min_ghz=requirements["frequency_min_ghz"],
        frequency_max_ghz=requirements["frequency_max_ghz"],
        target_s11_db=requirements["target_s11_db"], constraints=requirements,
    )
    artifacts: dict[str, str] = {}
    artifacts["requirements"] = str(workspace.save_artifact(
        "requirements", ArtifactType.REQUIREMENTS, requirements, "requirements_agent"))

    chief.start_task("task_research")
    evidence_db = EvidenceDatabase(root / "research" / "evidence.db")
    ingestion = PaperIngestionEngine(root / "research")
    paper_summaries: list[dict[str, Any]] = []
    for paper in papers or []:
        summary = ingestion.ingest_paper(paper)
        summary["claims_added"] = evidence_db.add_paper_claims(summary)
        paper_summaries.append(summary)
    coverage = SearchCoverage(0, 0, len(paper_summaries), len(paper_summaries), 0)
    evidence_db.record_coverage(prompt, coverage)
    evidence = {
        "mode": "LOCAL_ONLY", "papers": paper_summaries,
        "coverage": coverage.to_dict(), "conflicts": evidence_db.detect_conflicts(),
        "external_literature_search": "NOT_RUN: no paid or remote search service is used by default.",
    }
    artifacts["evidence"] = str(workspace.save_artifact("evidence", ArtifactType.EVIDENCE, evidence, "research_agent"))
    evidence_db.close()
    chief.complete_task("task_research", {"papers": len(paper_summaries)})

    chief.start_task("task_architecture")
    agent = RFArchitectureAgent()
    requested = _topologies(requirements["candidate_topologies"], requirements["wearable"])
    candidates = agent.full_evaluation(
        requirements["frequency_min_ghz"], requirements["frequency_max_ghz"],
        topologies=requested or None,
    )
    selected = candidates["selected"]
    selected["initial_estimate"] = candidates["initial_sizing"]
    selected["evidence_limit"] = "Topology selection is deterministic screening, not an EM result."
    artifacts["candidate_architectures"] = str(workspace.save_artifact(
        "candidate_architectures", ArtifactType.CANDIDATE_ARCHITECTURES, candidates, "rf_architecture_agent"))
    artifacts["selected_architecture"] = str(workspace.save_artifact(
        "selected_architecture", ArtifactType.SELECTED_ARCHITECTURE, selected, "rf_architecture_agent"))
    chief.complete_task("task_architecture", {"topology": selected["topology"]})

    chief.start_task("task_geometry")
    initial_parameters = candidates["initial_sizing"]["parameters"]
    parameter_records = [_parameter_record(name, value) for name, value in initial_parameters.items()]
    design_ir = {
        "schema_version": "planning-1.0", "topology": selected["topology"],
        "parameters": parameter_records,
        "execution_readiness": (
            "CST_COMPILER_AVAILABLE" if selected["topology"] in _SUPPORTED_CST_TOPOLOGIES
            else "CST_COMPILER_UNAVAILABLE_FOR_SELECTED_TOPOLOGY"
        ),
        "note": "This is a parameterized initial-design plan, not a CST geometry or simulation result.",
    }
    artifacts["design_ir"] = str(workspace.save_artifact("design_ir", ArtifactType.DESIGN_IR, design_ir, "geometry_agent"))
    artifacts["parameters"] = str(workspace.save_artifact(
        "parameters", ArtifactType.PARAMETERS, {"parameters": parameter_records}, "geometry_agent"))
    chief.complete_task("task_geometry", {"readiness": design_ir["execution_readiness"]})

    if mode == "dry-run":
        chief.block_task("task_simulation", "dry-run validates planning only; no RF simulation was requested")
        validation = {
            "valid": True, "mode": mode, "simulation_performed": False,
            "status": "PLANNING_VALIDATED", "limitations": ["No CST or mock RF result exists."],
        }
        artifacts["validation"] = str(workspace.save_artifact("validation", ArtifactType.VALIDATION, validation, "validation_agent"))
        workspace.set_meta("stage", "dry_run_complete")
        workspace.close()
        return DesignRun(root, "planning_validated", mode, selected["topology"], artifacts, 0)

    chief.start_task("task_simulation")
    bounds = [
        ParameterBound(name=name, min_value=value * 0.7, max_value=value * 1.3, default_value=value)
        for name, value in initial_parameters.items() if isinstance(value, (int, float)) and value > 0
    ]
    goal = OptimizationGoalConfig(
        reference_impedance_ohm=requirements["target_impedance_ohm"],
        frequency_range=FrequencyRange(requirements["frequency_min_ghz"], requirements["frequency_max_ghz"]),
        early_stop_s11_db=requirements["target_s11_db"],
    )
    runner = (RealCSTRunner(project_path=cst_project_path) if mode == "cst"
              else MockCSTRunner(topology=selected["topology"], center_freq_ghz=requirements["center_frequency_hz"] / 1e9))
    pipeline = OptimizationPipeline(OptimizationPipelineConfig(
        project_name=root.name, topology_name=selected["topology"], goal=goal, bounds=bounds,
        output_dir=root / "optimization", max_iterations=max_iterations, execution_mode=mode,
    ), runner=runner)
    result = pipeline.run(initial_params={b.name: b.default_value for b in bounds})
    source = result["runner_label"]
    artifacts["simulation_result"] = str(workspace.save_artifact(
        "simulation_result", ArtifactType.SIMULATION_RESULT, result["initial"], "simulation_agent"))
    chief.complete_task("task_simulation", {"source": source, "simulations": result["total_simulations"]})

    chief.start_task("task_sensitivity")
    artifacts["sensitivity"] = str(workspace.save_artifact(
        "sensitivity", ArtifactType.SENSITIVITY, result["sensitivity"], "optimization_agent"))
    chief.complete_task("task_sensitivity")
    chief.start_task("task_optimization")
    artifacts["optimization_iteration"] = str(workspace.save_artifact(
        "optimization_iteration", ArtifactType.OPTIMIZATION_ITERATION, result, "optimization_agent"))
    CheckpointManager(root / "optimization").save(CheckpointData(
        project_name=root.name, topology_name=selected["topology"], status="completed",
        current_iteration=result["total_simulations"], latest_parameters=result["final"]["params"],
        latest_simulation_result=result["final"]["result"], best_cost=result["final"]["cost"],
        best_parameters=result["best_parameters"], best_result=result["final"]["result"],
    ))
    chief.complete_task("task_optimization", {"source": source})

    chief.start_task("task_validation")
    validation = {
        "valid": True, "mode": mode, "simulation_source": source,
        "simulation_performed": True, "real_cst": mode == "cst",
        "limitations": ([] if mode == "cst" else ["MOCK_SIMULATION is not electromagnetic ground truth."]),
    }
    artifacts["validation"] = str(workspace.save_artifact("validation", ArtifactType.VALIDATION, validation, "validation_agent"))
    chief.complete_task("task_validation")
    chief.start_task("task_report")
    report = _report(requirements, selected, result, validation)
    artifacts["report"] = str(workspace.save_artifact("final_report", ArtifactType.REPORT, report, "report_agent"))
    (root / "final" / "final_report.md").write_text(report["markdown"], encoding="utf-8")
    chief.complete_task("task_report")
    workspace.set_meta("stage", "completed")
    pipeline.cache.close()
    workspace.close()
    return DesignRun(root, "completed", mode, selected["topology"], artifacts, result["total_simulations"])


def project_status(project_dir: str | Path) -> dict[str, Any]:
    chief = ChiefOrchestrator.resume(project_dir)
    try:
        result = chief.status()
        result["artifacts"] = chief.workspace.list_artifacts()
        checkpoint = CheckpointManager(Path(project_dir) / "optimization").load()
        result["checkpoint"] = checkpoint.to_dict() if checkpoint else None
        return result
    finally:
        chief.workspace.close()


def _as_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _topologies(names: Any, wearable: bool) -> list[AntennaTopology]:
    raw = names if isinstance(names, list) else []
    if not raw and wearable:
        raw = ["pifa", "ifa", "meander", "frame_integrated"]
    parsed: list[AntennaTopology] = []
    for name in raw:
        try:
            parsed.append(AntennaTopology(str(name)))
        except ValueError:
            continue
    return parsed


def _parameter_record(name: str, value: Any) -> dict[str, Any]:
    numeric = float(value) if isinstance(value, (int, float)) else 0.0
    return {
        "name": name, "value": numeric, "minimum": numeric * 0.7 if numeric > 0 else 0.0,
        "maximum": numeric * 1.3 if numeric > 0 else 0.0, "step": max(numeric * 0.02, 0.01),
        "unit": "mm" if name.endswith("_mm") else "dimensionless",
        "role": "geometry", "rf_effect": "INITIAL_ESTIMATE; verify with sensitivity and CST.",
    }


def _report(requirements: dict[str, Any], selected: dict[str, Any], result: dict[str, Any], validation: dict[str, Any]) -> dict[str, Any]:
    initial = result["initial"]
    final = result["final"]
    source = result["runner_label"]
    markdown = "\n".join([
        "# Prompt2CST Design Report", "",
        f"- Topology: `{selected['topology']}`", f"- Simulation source: `{source}`",
        f"- Target band: {requirements['frequency_min_ghz']:.4f}–{requirements['frequency_max_ghz']:.4f} GHz", "",
        "## Initial and final metrics", "",
        "| Metric | Initial | Final | Evidence |", "|---|---:|---:|---|",
        f"| Resonance (GHz) | {initial['result'].get('f_res_ghz', 'n/a')} | {final['result'].get('f_res_ghz', 'n/a')} | {source} |",
        f"| S11 (dB) | {initial['result'].get('s11_db', 'n/a')} | {final['result'].get('s11_db', 'n/a')} | {source} |",
        f"| Impedance (ohm) | {initial['result'].get('z_real', 'n/a')} + j{initial['result'].get('z_imag', 'n/a')} | {final['result'].get('z_real', 'n/a')} + j{final['result'].get('z_imag', 'n/a')} | {source} |",
        "", "## Limitations", "",
        *[f"- {item}" for item in validation["limitations"]],
    ])
    return {"markdown": markdown, "validation": validation, "initial": initial, "final": final}
