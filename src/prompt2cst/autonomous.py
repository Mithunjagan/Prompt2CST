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
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import yaml

from .antenna_knowledge import load_antenna_knowledge_base
from .architect import AntennaTopology, RFArchitectureAgent
from .cost_guard import CostGuard
from .datasets import FacultyDataset
from .evidence import EvidenceDatabase, SearchCoverage
from .local_ai import confirm_prompt_family
from .openems_backend import (
    OpenEMSProject,
    backend_status,
    build_project,
    execute_project,
    pifa_dimensions,
    pifa_search_parameters,
    sampled_s11_band,
    search_pifa,
    verify_domain_convergence,
    verify_mesh_convergence,
    write_project,
)
from .optimizer.checkpoint import CheckpointData, CheckpointManager
from .optimizer.pipeline import OptimizationPipeline, OptimizationPipelineConfig
from .optimizer.runner import MockCSTRunner, RealCSTRunner
from .optimizer.schema import FrequencyRange, OptimizationGoalConfig, ParameterBound
from .orchestrator import ChiefOrchestrator
from .papers import PaperIngestionEngine
from .prompt_intent import resolve_explicit_family
from .shared_state import ArtifactType, ProjectWorkspace

_SUPPORTED_CST_TOPOLOGIES = {"patch", "monopole", "dipole"}
_SUPPORTED_OPENEMS_TOPOLOGIES = {"pifa", "helix", "yagi_uda", "horn", "vivaldi"}
_FREQ_RE = re.compile(
    r"(?<![\d.])(?P<range_min>\d+(?:\.\d+)?)\s*(?:-|–|to)\s*"
    r"(?P<range_max>\d+(?:\.\d+)?)\s*(?P<range_unit>ghz|gigahertz|mhz|megahertz)\b"
    r"|(?<![\d.])(?P<single>\d+(?:\.\d+)?)\s*"
    r"(?P<single_unit>ghz|gigahertz|mhz|megahertz)\b",
    re.I,
)
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
    specified_families = spec.get("candidate_topologies", [])
    if not isinstance(specified_families, list) or not all(
        isinstance(name, str) for name in specified_families
    ):
        raise ValueError("candidate_topologies must be a list of antenna-family names")
    explicit_family = resolve_explicit_family(prompt, specified_families)
    canonical_specified = [
        load_antenna_knowledge_base().family(name).family
        for name in specified_families
    ]
    req = spec.get("requirements", {}) if isinstance(spec.get("requirements"), dict) else {}
    frequency = req.get("frequency", {}) if isinstance(req.get("frequency"), dict) else {}
    text = prompt.lower()
    match = _FREQ_RE.search(prompt)
    if match and match.group("range_min"):
        scale = 1e-3 if match.group("range_unit").lower() in {"mhz", "megahertz"} else 1.0
        min_ghz = float(match.group("range_min")) * scale
        max_ghz = float(match.group("range_max")) * scale
    elif match:
        scale = 1e-3 if match.group("single_unit").lower() in {"mhz", "megahertz"} else 1.0
        center = float(match.group("single")) * scale
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
        "candidate_topologies": (
            canonical_specified or ([explicit_family] if explicit_family else [])
        ),
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
    datasets: list[str | Path] | None = None,
    spec: dict[str, Any] | None = None,
    cst_project_path: str | None = None,
    max_iterations: int = 15,
    progress: Callable[[str], None] | None = None,
    use_local_ai: bool = False,
) -> DesignRun:
    """Execute a local-first design run and write all audit artifacts."""
    if mode not in {"dry-run", "mock", "cst", "openems", "openems-simulate"}:
        raise ValueError("mode must be dry-run, mock, cst, openems, or openems-simulate")
    if mode == "cst" and not cst_project_path:
        raise ValueError("--mode cst requires --project-path to a parameterized CST project")

    requirements = extract_requirements(prompt, spec)
    if use_local_ai:
        specified = (spec or {}).get("candidate_topologies", [])
        explicit = resolve_explicit_family(prompt, specified)
        local_ai = confirm_prompt_family(prompt, explicit)
        requirements["local_ai"] = local_ai.to_dict()
        if progress is not None:
            progress(f"Local Ollama family check: {local_ai.status}; deterministic plan retained")
    root = Path(project_dir).resolve()
    workspace = ProjectWorkspace(root)
    chief = ChiefOrchestrator(workspace=workspace, cost_guard=CostGuard())
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
    dataset_summaries: list[dict[str, Any]] = []
    for index, dataset_path in enumerate(datasets or [], start=1):
        dataset = FacultyDataset.load(dataset_path)
        summary = dataset.analyze(requirements["center_frequency_hz"] / 1e9)
        study_dir = root / "research" / "datasets" / f"dataset_{index:03d}"
        summary["artifacts"] = dataset.save_study(
            study_dir, requirements["center_frequency_hz"] / 1e9
        )
        dataset_summaries.append(summary)
    coverage = SearchCoverage(0, 0, len(paper_summaries), len(paper_summaries), 0)
    evidence_db.record_coverage(prompt, coverage)
    evidence = {
        "mode": "LOCAL_ONLY", "papers": paper_summaries, "datasets": dataset_summaries,
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
            else (
                "OPENEMS_GENERATOR_AVAILABLE"
                if selected["topology"] in _SUPPORTED_OPENEMS_TOPOLOGIES
                else "NO_GEOMETRY_GENERATOR_FOR_SELECTED_TOPOLOGY"
            )
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

    if mode in {"openems", "openems-simulate"}:
        topology = str(selected["topology"])
        if topology not in _SUPPORTED_OPENEMS_TOPOLOGIES:
            raise ValueError(
                f"openEMS generation is not implemented for {topology}; "
                f"supported: {sorted(_SUPPORTED_OPENEMS_TOPOLOGIES)}"
            )
        openems_dir = root / "openems"
        openems_project = build_project(
            topology, requirements["center_frequency_hz"],
            bandwidth_fraction=max(
                0.02,
                (requirements["frequency_max_ghz"] - requirements["frequency_min_ghz"])
                / (requirements["center_frequency_hz"] / 1e9),
            ),
        )
        generated = write_project(openems_project, openems_dir)
        artifacts["openems_plan"] = generated["plan"]
        artifacts["openems_script"] = generated["script"]
        if mode == "openems-simulate":
            chief.start_task("task_simulation")
            try:
                if progress is not None:
                    progress(f"Running initial {topology} openEMS FDTD simulation")
                execution = execute_project(openems_dir)
                measured = execution["result"]
                frequencies = measured["frequency_hz"]
                center_index = min(
                    range(len(frequencies)),
                    key=lambda index: abs(frequencies[index] - requirements["center_frequency_hz"]),
                )
                initial_s11 = measured["s11_db"][center_index]
                if progress is not None:
                    progress(f"Initial S11 at target: {initial_s11:.2f} dB")
                search = None
                simulation_count = 1
                selected_results_path = execution["results"]
                selected_project_hash = openems_project.canonical_sha256
                if topology == "pifa" and initial_s11 > requirements["target_s11_db"] and max_iterations > 1:
                    # Leave room for at least one mesh comparison and, when
                    # the budget permits, a separate air-domain comparison.
                    verification_reserve = min(
                        3 if max_iterations >= 4 else 2,
                        max(0, max_iterations - 2),
                    )
                    search = search_pifa(
                        requirements["center_frequency_hz"], root / "openems_search",
                        target_s11_db=requirements["target_s11_db"],
                        max_runs=min(max_iterations - 1 - verification_reserve, 25),
                        on_candidate=(
                            lambda candidate: progress(
                                f"PIFA length {candidate['length_scale']:.2f}, "
                                f"feed {candidate['feed_fraction']:.2f}: "
                                f"S11 {candidate['center_s11_db']:.2f} dB"
                            )
                            if progress is not None else None
                        ),
                    )
                    simulation_count += search["real_runs_this_call"]
                    artifacts["openems_search_summary"] = str(root / "openems_search" / "search_summary.json")
                    if search["best"]["center_s11_db"] < initial_s11:
                        selected_results_path = search["best"]["results"]
                        selected_project_hash = search["best"]["project_sha256"]
                        measured = json.loads(Path(selected_results_path).read_text(encoding="utf-8"))
                        frequencies = measured["frequency_hz"]
                        center_index = min(
                            range(len(frequencies)),
                            key=lambda index: abs(frequencies[index] - requirements["center_frequency_hz"]),
                        )
                        winner_dir = Path(selected_results_path).parent
                        artifacts["optimized_openems_plan"] = str(winner_dir / "openems_plan.json")
                        artifacts["optimized_openems_script"] = str(winner_dir / "run_openems.py")
            except Exception as exc:
                chief.fail_task("task_simulation", f"{type(exc).__name__}: {exc}")
                workspace.close()
                raise
            center_s11 = measured["s11_db"][center_index]
            target_met = center_s11 <= requirements["target_s11_db"]
            mesh_report = None
            mesh_root = Path(selected_results_path).parent
            while target_met and simulation_count < max_iterations:
                mesh_plan = OpenEMSProject.model_validate_json(
                    (mesh_root / "openems_plan.json").read_text(encoding="utf-8")
                )
                if mesh_plan.mesh_refinement_factor * 1.25 > 3.0:
                    break
                if progress is not None:
                    progress("Checking the selected result on a denser openEMS mesh")
                try:
                    mesh_report = verify_mesh_convergence(
                        mesh_root,
                        refinement_factor=1.25,
                    )
                except subprocess.TimeoutExpired:
                    mesh_report = {
                        "source": "OPENEMS_FDTD",
                        "status": "INCONCLUSIVE_TIMEOUT",
                        "real_runs_this_call": 1,
                        "baseline_results": selected_results_path,
                        "refined_results": None,
                    }
                    (mesh_root / "mesh_convergence.json").write_text(
                        json.dumps(mesh_report, indent=2) + "\n", encoding="utf-8"
                    )
                    simulation_count += 1
                    artifacts["mesh_convergence"] = str(mesh_root / "mesh_convergence.json")
                    if progress is not None:
                        progress("Mesh comparison timed out; retaining the last completed solver result")
                    break
                except Exception as exc:
                    chief.fail_task("task_simulation", f"mesh check: {type(exc).__name__}: {exc}")
                    workspace.close()
                    raise
                simulation_count += mesh_report["real_runs_this_call"]
                if progress is not None:
                    progress(f"Mesh comparison: {mesh_report['status']}")
                artifacts["mesh_convergence"] = str(mesh_root / "mesh_convergence.json")
                if mesh_report["status"] == "INCONCLUSIVE_TIMEOUT":
                    break
                selected_results_path = mesh_report["refined_results"]
                selected_project_hash = mesh_report["refined_project_sha256"]
                refined_dir = Path(selected_results_path).parent
                artifacts["optimized_openems_plan"] = str(refined_dir / "openems_plan.json")
                artifacts["optimized_openems_script"] = str(refined_dir / "run_openems.py")
                measured = json.loads(Path(selected_results_path).read_text(encoding="utf-8"))
                frequencies = measured["frequency_hz"]
                center_index = min(
                    range(len(frequencies)),
                    key=lambda index: abs(frequencies[index] - requirements["center_frequency_hz"]),
                )
                center_s11 = measured["s11_db"][center_index]
                target_met = center_s11 <= requirements["target_s11_db"]
                if (
                    topology == "pifa" and not target_met
                    and simulation_count + 1 < max_iterations
                ):
                    failed_plan = OpenEMSProject.model_validate_json(
                        (refined_dir / "openems_plan.json").read_text(encoding="utf-8")
                    )
                    seed_length, seed_feed = pifa_search_parameters(failed_plan)
                    recovery_dir = root / (
                        f"openems_recovery_mesh_{failed_plan.mesh_refinement_factor:.3f}"
                    )
                    try:
                        recovery = search_pifa(
                            requirements["center_frequency_hz"], recovery_dir,
                            length_scales=(seed_length,),
                            feed_fractions=(seed_feed,),
                            target_s11_db=requirements["target_s11_db"],
                            max_runs=min(max_iterations - simulation_count - 1, 6),
                            mesh_refinement_factor=failed_plan.mesh_refinement_factor,
                            on_candidate=(
                                lambda candidate: progress(
                                    f"Refined-mesh PIFA retune: S11 "
                                    f"{candidate['center_s11_db']:.2f} dB"
                                ) if progress is not None else None
                            ),
                        )
                    except Exception as exc:
                        chief.fail_task(
                            "task_simulation", f"refined-mesh retune: {type(exc).__name__}: {exc}"
                        )
                        workspace.close()
                        raise
                    simulation_count += recovery["real_runs_this_call"]
                    artifacts["openems_recovery_search_summary"] = str(
                        recovery_dir / "search_summary.json"
                    )
                    if recovery["best"]["meets_target"]:
                        search = recovery
                        selected_results_path = recovery["best"]["results"]
                        selected_project_hash = recovery["best"]["project_sha256"]
                        mesh_root = Path(selected_results_path).parent
                        artifacts["optimized_openems_plan"] = str(
                            mesh_root / "openems_plan.json"
                        )
                        artifacts["optimized_openems_script"] = str(
                            mesh_root / "run_openems.py"
                        )
                        measured = json.loads(
                            Path(selected_results_path).read_text(encoding="utf-8")
                        )
                        frequencies = measured["frequency_hz"]
                        center_index = min(
                            range(len(frequencies)),
                            key=lambda index: abs(
                                frequencies[index] - requirements["center_frequency_hz"]
                            ),
                        )
                        center_s11 = measured["s11_db"][center_index]
                        target_met = center_s11 <= requirements["target_s11_db"]
                        mesh_report = None
                        if progress is not None:
                            progress("PIFA recovered the target; rechecking the new winner")
                        continue
                if mesh_report["status"] == "CONVERGED":
                    break
                mesh_root = refined_dir
            domain_report = None
            if (
                target_met
                and mesh_report is not None
                and mesh_report["status"] == "CONVERGED"
                and simulation_count < max_iterations
            ):
                if progress is not None:
                    progress("Checking the selected result in a larger openEMS air domain")
                try:
                    domain_report = verify_domain_convergence(
                        Path(selected_results_path).parent,
                        padding_factor=1.25,
                    )
                except subprocess.TimeoutExpired:
                    domain_report = {
                        "source": "OPENEMS_FDTD",
                        "status": "INCONCLUSIVE_TIMEOUT",
                        "real_runs_this_call": 1,
                        "enlarged_results": None,
                    }
                    (Path(selected_results_path).parent / "domain_convergence.json").write_text(
                        json.dumps(domain_report, indent=2) + "\n", encoding="utf-8"
                    )
                except Exception as exc:
                    chief.fail_task("task_simulation", f"domain check: {type(exc).__name__}: {exc}")
                    workspace.close()
                    raise
                simulation_count += domain_report["real_runs_this_call"]
                domain_root = Path(selected_results_path).parent
                artifacts["domain_convergence"] = str(domain_root / "domain_convergence.json")
                if progress is not None:
                    progress(f"Domain comparison: {domain_report['status']}")
                if domain_report["status"] != "INCONCLUSIVE_TIMEOUT":
                    selected_results_path = domain_report["enlarged_results"]
                    selected_project_hash = domain_report["enlarged_project_sha256"]
                    enlarged_dir = Path(selected_results_path).parent
                    artifacts["optimized_openems_plan"] = str(enlarged_dir / "openems_plan.json")
                    artifacts["optimized_openems_script"] = str(enlarged_dir / "run_openems.py")
                    measured = json.loads(Path(selected_results_path).read_text(encoding="utf-8"))
                    frequencies = measured["frequency_hz"]
                    center_index = min(
                        range(len(frequencies)),
                        key=lambda index: abs(
                            frequencies[index] - requirements["center_frequency_hz"]
                        ),
                    )
                    center_s11 = measured["s11_db"][center_index]
                    target_met = center_s11 <= requirements["target_s11_db"]
            artifacts["openems_results"] = selected_results_path
            summary = {
                "source": "OPENEMS_FDTD",
                "project_sha256": selected_project_hash,
                "frequency_hz": frequencies[center_index],
                "s11_db": center_s11,
                "z_real_ohm": measured["z_real_ohm"][center_index],
                "z_imag_ohm": measured["z_imag_ohm"][center_index],
                "best_band_s11_db": measured["best_s11_db"],
                "target_s11_db": requirements["target_s11_db"],
                "target_met": target_met,
                "sampled_s11_band": sampled_s11_band(
                    measured, requirements["center_frequency_hz"],
                    requirements["target_s11_db"],
                ),
                "raw_results": selected_results_path,
                "simulations": simulation_count,
                "mesh_convergence": mesh_report["status"] if mesh_report is not None else "NOT_RUN",
                "domain_convergence": domain_report["status"] if domain_report is not None else "NOT_RUN",
            }
            if topology == "pifa":
                selected_plan_path = artifacts.get("optimized_openems_plan", artifacts["openems_plan"])
                selected_plan = OpenEMSProject.model_validate_json(
                    Path(selected_plan_path).read_text(encoding="utf-8")
                )
                summary["dimensions_mm"] = pifa_dimensions(selected_plan)
            artifacts["simulation_result"] = str(workspace.save_artifact(
                "simulation_result", ArtifactType.SIMULATION_RESULT,
                summary, "openems_solver",
            ))
            chief.complete_task("task_simulation", {"source": "OPENEMS_FDTD", "simulations": simulation_count})
            chief.block_task("task_sensitivity", "formal sensitivity analysis was not performed")
            if search is not None:
                chief.start_task("task_optimization")
                artifacts["optimization_iteration"] = str(workspace.save_artifact(
                    "optimization_iteration", ArtifactType.OPTIMIZATION_ITERATION,
                    search, "openems_pifa_search",
                ))
                chief.complete_task("task_optimization", {"source": "OPENEMS_FDTD", "simulations": simulation_count})
            else:
                chief.block_task("task_optimization", "no parameter search was needed or available")
            chief.start_task("task_validation")
            validation = {
                "valid": True, "mode": mode, "simulation_performed": True,
                "simulation_source": "OPENEMS_FDTD",
                "status": (
                    "TARGET_MET_MESH_AND_DOMAIN_CONVERGED"
                    if target_met and mesh_report is not None
                    and mesh_report["status"] == "CONVERGED"
                    and domain_report is not None and domain_report["status"] == "CONVERGED"
                    else "DOMAIN_NOT_CONVERGED"
                    if domain_report is not None and domain_report["status"] == "NOT_CONVERGED"
                    else "DOMAIN_INCONCLUSIVE"
                    if domain_report is not None and domain_report["status"] == "INCONCLUSIVE_TIMEOUT"
                    else
                    "TARGET_MET_MESH_CONVERGED"
                    if target_met and mesh_report is not None and mesh_report["status"] == "CONVERGED"
                    else "S11_THRESHOLD_MET_MESH_INCONCLUSIVE"
                    if target_met and mesh_report is not None and mesh_report["status"] == "INCONCLUSIVE_TIMEOUT"
                    else "TARGET_UNMET_MESH_INCONCLUSIVE"
                    if not target_met and mesh_report is not None and mesh_report["status"] == "INCONCLUSIVE_TIMEOUT"
                    else "TARGET_UNMET_MESH_NOT_CONVERGED"
                    if not target_met and mesh_report is not None and mesh_report["status"] != "CONVERGED"
                    else "MESH_NOT_CONVERGED"
                    if mesh_report is not None and mesh_report["status"] != "CONVERGED"
                    else "S11_THRESHOLD_MET_MESH_UNVERIFIED"
                    if target_met else "TARGET_UNMET"
                ),
                "target_met": target_met,
                "mesh_convergence": mesh_report["status"] if mesh_report is not None else "NOT_RUN",
                "domain_convergence": domain_report["status"] if domain_report is not None else "NOT_RUN",
                "limitations": [
                    "S11 and port impedance were simulated; mesh and domain convergence are reported separately.",
                    "Gain, radiation efficiency, pattern, tolerances, and fabrication are not verified.",
                ],
            }
            artifacts["validation"] = str(workspace.save_artifact(
                "validation", ArtifactType.VALIDATION, validation, "validation_agent"
            ))
            chief.complete_task("task_validation")
            chief.start_task("task_report")
            report_text = (
                f"# openEMS antenna simulation\n\n"
                f"- Family: {topology}\n"
                f"- Solver: openEMS FDTD\n"
                f"- Solver runs: {simulation_count}\n"
                f"- Frequency: {frequencies[center_index] / 1e9:.4f} GHz\n"
                f"- S11: {center_s11:.2f} dB (target {requirements['target_s11_db']:.2f} dB)\n"
                f"- Impedance: {summary['z_real_ohm']:.2f} + j{summary['z_imag_ohm']:.2f} ohm\n"
                f"- Target met: {'yes' if target_met else 'no'}\n\n"
                f"- Mesh convergence: {summary['mesh_convergence']}\n"
                f"- Domain convergence: {summary['domain_convergence']}\n\n"
                f"Mesh convergence: {mesh_report['status'] if mesh_report is not None else 'not run'}. "
                "Gain, efficiency, pattern, and fabrication are unverified.\n"
            )
            if topology == "pifa":
                dims = summary["dimensions_mm"]
                report_text += (
                    "\n## Simulated PIFA geometry\n\n"
                    f"- Radiator: {dims['radiator_length_mm']:.2f} × {dims['radiator_width_mm']:.2f} mm\n"
                    f"- Height above ground: {dims['radiator_height_mm']:.2f} mm\n"
                    f"- Ground: {dims['ground_length_mm']:.2f} × {dims['ground_width_mm']:.2f} mm\n"
                    f"- Short wall width: {dims['short_wall_width_mm']:.2f} mm\n"
                    f"- Feed clearance from short wall: {dims['feed_clearance_from_short_wall_mm']:.2f} mm\n"
                    "- Conductors are ideal PEC sheets; copper thickness, connector, enclosure, and mounting are not modelled.\n"
                )
            artifacts["report"] = str(workspace.save_artifact(
                "final_report", ArtifactType.REPORT,
                {"markdown": report_text, "source": "OPENEMS_FDTD"}, "report_agent"
            ))
            (root / "final" / "final_report.md").write_text(report_text, encoding="utf-8")
            chief.complete_task("task_report")
            workspace.set_meta("stage", "openems_simulated")
            workspace.close()
            return DesignRun(root, "openems_simulated", mode, topology, artifacts, simulation_count)
        status = backend_status()
        validation = {
            "valid": True,
            "mode": mode,
            "simulation_performed": False,
            "status": (
                "OPENEMS_PROJECT_READY"
                if status["available"]
                else "OPENEMS_BACKEND_UNAVAILABLE"
            ),
            "project_sha256": generated["sha256"],
            "backend": status,
            "limitations": [
                "A deterministic openEMS project was generated but has not been simulated.",
                "No S11, impedance, gain, efficiency, pattern, or SAR result exists yet.",
            ],
        }
        artifacts["validation"] = str(workspace.save_artifact(
            "validation", ArtifactType.VALIDATION, validation, "validation_agent"
        ))
        chief.block_task(
            "task_simulation",
            "openEMS project generated; solver execution and result validation remain",
        )
        workspace.set_meta("stage", "openems_project_generated")
        workspace.close()
        return DesignRun(
            root, "openems_project_generated", mode, topology, artifacts, 0
        )

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
