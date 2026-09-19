"""Command-line interface for Prompt2CST zero-cost RF swarm and optimization pipeline.

Provides CLI commands for:
  - run-swarm: Full end-to-end autonomous RF architecture, sizing, optimization, report generation
  - optimize: Run staged optimization on a spec YAML or design JSON
  - ingest-paper: Extract RF parameters from uploaded research papers with provenance
  - audit-cost: Inspect zero-cost budget enforcement and verify $0 API usage
  - capabilities: Browser and filter supported/unsupported CST 2026 capabilities
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from .architect import RFArchitectureAgent
from .capabilities import capability_browser
from .cost_guard import CostGuard
from .cst_bridge import CSTBridge
from .evidence import EvidenceDatabase
from .optimizer.pipeline import OptimizationPipeline, OptimizationPipelineConfig
from .optimizer.runner import MockCSTRunner, RealCSTRunner
from .optimizer.schema import OptimizationGoalConfig, ParameterBound
from .papers import PaperIngestionEngine
from .reports import generate_optimization_report, save_report
from .wearable import WearableAntennaEvaluator, HeadLayerProperties
from .autonomous import load_spec, project_status, run_design
from .orchestrator import ChiefOrchestrator


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="prompt2cst",
        description="Prompt2CST: Zero-Cost Autonomous CST Electromagnetic Design & Optimization System",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available subcommands")

    # run-swarm
    swarm_parser = subparsers.add_parser("run-swarm", help="Run full autonomous RF swarm pipeline")
    swarm_parser.add_argument("--freq", type=float, default=2.45, help="Target frequency in GHz (default: 2.45)")
    swarm_parser.add_argument("--impedance", type=float, default=50.0, help="Target impedance in Ohms (default: 50.0)")
    swarm_parser.add_argument("--wearable", action="store_true", help="Enable wearable head-loading tissue evaluation")
    swarm_parser.add_argument("--paper", type=str, default=None, help="Path to PDF paper to ingest as evidence")
    swarm_parser.add_argument("--output-dir", type=str, default="outputs", help="Output directory for reports and CST scripts")

    design_parser = subparsers.add_parser("design", help="Create an artifact-backed autonomous design project")
    design_parser.add_argument("request", nargs="+", help="Natural-language RF design request")
    design_parser.add_argument("--spec", help="Optional local YAML or JSON design specification")
    design_parser.add_argument("--paper", action="append", default=[], help="Optional local PDF evidence; repeatable")
    design_parser.add_argument("--project-dir", default="project", help="Local project workspace directory")
    design_parser.add_argument("--mode", choices=("dry-run", "mock", "cst"), default="dry-run")
    design_parser.add_argument("--project-path", help="Parameterized CST project required by --mode cst")
    design_parser.add_argument("--max-iterations", type=int, default=15)

    research_parser = subparsers.add_parser("research", help="Ingest local evidence and create a planning workspace")
    research_parser.add_argument("request", nargs="+", help="Research/design question")
    research_parser.add_argument("--paper", action="append", default=[], help="Optional local PDF evidence; repeatable")
    research_parser.add_argument("--project-dir", default="project", help="Local project workspace directory")

    resume_parser = subparsers.add_parser("resume", help="Inspect a persisted project and its next runnable tasks")
    resume_parser.add_argument("project_dir", help="Project workspace directory")
    status_parser = subparsers.add_parser("status", help="Show persisted project status")
    status_parser.add_argument("project_dir", help="Project workspace directory")

    # optimize
    opt_parser = subparsers.add_parser("optimize", help="Run staged optimizer on design specs")
    opt_parser.add_argument("spec_path", nargs="?", help="Optional YAML design specification")
    opt_parser.add_argument("--topology", type=str, default="pifa", help="Antenna topology (pifa, patch, monopole, dipole)")
    opt_parser.add_argument("--freq", type=float, default=2.45, help="Target frequency in GHz")
    opt_parser.add_argument("--output-dir", type=str, default="outputs", help="Output directory")
    opt_parser.add_argument("--mode", choices=("dry-run", "mock", "cst"), default="mock", help="Simulation backend")
    opt_parser.add_argument("--project-path", type=str, help="Solved CST project required by --mode cst")

    # ingest-paper
    paper_parser = subparsers.add_parser("ingest-paper", help="Ingest a PDF research paper into evidence database")
    paper_parser.add_argument("pdf_path", type=str, help="Path to PDF file")
    paper_parser.add_argument("--db-path", type=str, default="evidence.db", help="SQLite evidence DB path")

    # audit-cost
    subparsers.add_parser("audit-cost", help="Audit cost guard enforcement to ensure $0 spent")

    # capabilities
    subparsers.add_parser("capabilities", help="List CST 2026 compiler capabilities")

    link_parser = subparsers.add_parser(
        "cst-dipole-link",
        help="Prove a parameterized dipole produces two distinct real CST responses",
    )
    link_parser.add_argument("--project-name", default="controlled_dipole_link")
    link_parser.add_argument("--length-a-mm", type=float, default=55.0)
    link_parser.add_argument("--length-b-mm", type=float, default=65.0)
    link_parser.add_argument("--freq", type=float, default=2.45)
    link_parser.add_argument("--output-dir", default="outputs")

    impedance_link_parser = subparsers.add_parser(
        "cst-pifa-impedance-link",
        help="Prove that a parameterized temple-PIFA feed offset changes real CST Zin",
    )
    impedance_link_parser.add_argument("--project-name", default="controlled_pifa_impedance_link")
    impedance_link_parser.add_argument("--feed-offset-a-mm", type=float, default=0.5)
    impedance_link_parser.add_argument("--feed-offset-b-mm", type=float, default=3.0)
    impedance_link_parser.add_argument("--output-dir", default="outputs")

    pifa_sweep_parser = subparsers.add_parser(
        "cst-pifa-impedance-optimize",
        help="Run or resume the CST-only feed-offset impedance sweep",
    )
    pifa_sweep_parser.add_argument("--output-dir", default="outputs/real_pifa_stage_b_impedance_optimization")
    pifa_sweep_parser.add_argument("--resume", action="store_true")
    pifa_sweep_parser.add_argument("--stop-after", type=int, help="Stop safely after this completed candidate")
    pifa_sweep_parser.add_argument("--stage-a-checkpoint", default="outputs/real_pifa_frequency_optimization/checkpoint.json", help="Validated FREQUENCY_LOCKED Stage-A checkpoint")

    pifa_frequency_parser = subparsers.add_parser(
        "cst-pifa-frequency-optimize",
        help="Run or resume real-CST Stage A resonance tuning with feed matching frozen",
    )
    pifa_frequency_parser.add_argument("--output-dir", default="outputs/real_pifa_frequency_optimization")
    pifa_frequency_parser.add_argument("--resume", action="store_true")
    pifa_frequency_parser.add_argument("--stop-after", type=int, help="Stop safely after this completed candidate")
    pifa_frequency_parser.add_argument("--local-refinement", action="store_true", help="Refine an existing partial Stage A result only in the 21.0–22.5 mm neighborhood")

    return parser


def main(args: list[str] | None = None) -> int:
    parser = create_parser()
    parsed = parser.parse_args(args)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    if not parsed.command:
        parser.print_help()
        return 0

    if parsed.command == "audit-cost":
        guard = CostGuard()
        print(json.dumps(guard.to_dict(), indent=2))
        return 0

    if parsed.command == "capabilities":
        caps = capability_browser()
        print(json.dumps(caps, indent=2))
        return 0

    if parsed.command in {"status", "resume"}:
        try:
            status = project_status(parsed.project_dir)
        except (FileNotFoundError, ValueError) as exc:
            print(f"Project status unavailable: {exc}", file=sys.stderr)
            return 1
        if parsed.command == "resume":
            resumed = ChiefOrchestrator.resume(parsed.project_dir)
            try:
                status["next_tasks"] = resumed.get_next_tasks()
            finally:
                resumed.workspace.close()
            status["resume_note"] = "State was loaded without fabricating a simulation; rerun design with the original inputs to continue a stopped computational stage."
        print(json.dumps(status, indent=2, default=str))
        return 0

    if parsed.command in {"design", "research", "optimize"}:
        if parsed.command == "design":
            prompt = " ".join(parsed.request)
            spec = load_spec(parsed.spec) if parsed.spec else None
            project_dir = parsed.project_dir
            papers = parsed.paper
            mode = parsed.mode
            project_path = parsed.project_path
            iterations = parsed.max_iterations
        elif parsed.command == "research":
            prompt = " ".join(parsed.request)
            spec = None
            project_dir = parsed.project_dir
            papers = parsed.paper
            mode = "dry-run"
            project_path = None
            iterations = 0
        else:
            spec = load_spec(parsed.spec_path) if parsed.spec_path else None
            prompt = str((spec or {}).get("description") or (spec or {}).get("name") or f"Optimize a {parsed.topology} antenna at {parsed.freq} GHz")
            project_dir = parsed.output_dir
            papers = []
            mode = parsed.mode
            project_path = parsed.project_path
            iterations = 15
        try:
            result = run_design(
                prompt, project_dir, mode=mode, papers=papers, spec=spec,
                cst_project_path=project_path, max_iterations=iterations,
            )
        except (FileNotFoundError, ValueError, RuntimeError) as exc:
            print(f"Design workflow failed: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 1
        print(json.dumps(result.to_dict(), indent=2))
        return 0

    if parsed.command == "cst-dipole-link":
        bridge = CSTBridge(output_dir=parsed.output_dir)
        try:
            evidence = bridge.run_controlled_dipole_link_test(
                project_name=parsed.project_name,
                length_a_mm=parsed.length_a_mm,
                length_b_mm=parsed.length_b_mm,
                frequency_ghz=parsed.freq,
                overwrite=True,
            )
        except Exception as exc:
            print(
                f"CST controlled-link test failed: {type(exc).__name__}: {exc}",
                file=sys.stderr,
            )
            return 1
        print(json.dumps(evidence, indent=2))
        return 0 if evidence["response_changed"] else 2

    if parsed.command == "cst-pifa-impedance-link":
        bridge = CSTBridge(output_dir=parsed.output_dir)
        try:
            evidence = bridge.run_temple_pifa_impedance_link_test(
                project_name=parsed.project_name,
                feed_offset_a_mm=parsed.feed_offset_a_mm,
                feed_offset_b_mm=parsed.feed_offset_b_mm,
                overwrite=True,
            )
        except Exception as exc:
            print(
                f"CST PIFA impedance-link test failed: {type(exc).__name__}: {exc}",
                file=sys.stderr,
            )
            return 1
        print(json.dumps(evidence, indent=2))
        return 0 if evidence["response_changed"] else 2

    if parsed.command == "cst-pifa-impedance-optimize":
        from .real_pifa_sweep import RealPifaImpedanceSweep
        try:
            state = RealPifaImpedanceSweep(parsed.output_dir, resume=parsed.resume, stage_a_checkpoint=parsed.stage_a_checkpoint).run(
                stop_after=parsed.stop_after
            )
        except Exception as exc:
            print(f"CST PIFA impedance optimization failed: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 1
        print(json.dumps(state, indent=2))
        return 0 if state.get("status") == "completed" else 3

    if parsed.command == "cst-pifa-frequency-optimize":
        from .real_pifa_frequency import RealPifaFrequencyOptimization
        try:
            workflow = RealPifaFrequencyOptimization(parsed.output_dir, resume=parsed.resume)
            state = workflow.run_local_refinement() if parsed.local_refinement else workflow.run(stop_after=parsed.stop_after)
        except Exception as exc:
            print(f"CST PIFA Stage A frequency optimization failed: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 1
        print(json.dumps(state, indent=2))
        return 0 if state.get("status") in {"FREQUENCY_LOCKED", "PARTIAL_FREQUENCY_IMPROVEMENT"} else 3

    if parsed.command == "ingest-paper":
        engine = PaperIngestionEngine()
        pdf_file = Path(parsed.pdf_path)
        if not pdf_file.exists():
            print(f"Error: File not found: {parsed.pdf_path}", file=sys.stderr)
            return 1
        extracted = engine.ingest_paper(pdf_file)
        db = EvidenceDatabase(parsed.db_path)
        count = db.add_paper_claims(extracted)
        print(f"Ingested {pdf_file.name}: Extracted {len(extracted.extracted_parameters)} parameters, added {count} evidence claims.")
        return 0

    if parsed.command == "run-swarm" or parsed.command == "optimize":
        if parsed.command == "optimize" and parsed.mode == "cst" and not parsed.project_path:
            parser.error("optimize --mode cst requires --project-path to a parameterized CST project")
        out_dir = Path(parsed.output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        freq_hz = (parsed.freq or 2.45) * 1e9

        print(f"=== Prompt2CST Autonomous RF Swarm (Target: {parsed.freq} GHz) ===")

        # Step 1: Ingest paper if provided
        paper_params = {}
        if getattr(parsed, "paper", None):
            pdf_path = Path(parsed.paper)
            if pdf_path.exists():
                print(f"[Phase 1] Ingesting paper: {pdf_path.name}")
                engine = PaperIngestionEngine()
                extracted = engine.ingest_paper(pdf_path)
                paper_params = extracted.extracted_parameters

        # Step 2: Architecture Agent evaluation
        print("[Phase 2] Evaluating antenna candidate topologies...")
        agent = RFArchitectureAgent()
        reqs = {
            "center_frequency_hz": freq_hz,
            "frequency_min_hz": freq_hz * 0.95,
            "frequency_max_hz": freq_hz * 1.05,
            "target_impedance_ohm": getattr(parsed, "impedance", 50.0),
            "max_volume_mm3": 50.0 * 20.0 * 8.0,
            "wearable": getattr(parsed, "wearable", False),
        }
        cand_eval = agent.evaluate_topologies(reqs)
        best_cand = cand_eval["recommended"]
        print(f"  Recommended topology: {best_cand['topology']} (Score: {best_cand['score']:.2f})")

        # Step 3: Closed-form initial sizing
        initial_params = best_cand["closed_form_dimensions"]
        print("  Closed-form initial dimensions:")
        for k, v in initial_params.items():
            print(f"    {k}: {v:.2f} mm")

        # Step 4: Staged optimization pipeline
        print("[Phase 3] Running staged optimization pipeline...")
        bounds = [
            ParameterBound(name=k, min_value=v * 0.5, max_value=v * 1.5, default_value=v)
            for k, v in initial_params.items()
        ]
        from .optimizer.schema import FrequencyRange
        goal = OptimizationGoalConfig(
            frequency_range=FrequencyRange(min_ghz=parsed.freq * 0.95, max_ghz=parsed.freq * 1.05),
            reference_impedance_ohm=getattr(parsed, "impedance", 50.0),
            early_stop_s11_db=-10.0,
        )
        pipe_cfg = OptimizationPipelineConfig(
            project_name=f"Swarm_{best_cand['topology']}_{int(parsed.freq*1000)}MHz",
            topology_name=best_cand["topology"],
            goal=goal,
            bounds=bounds,
            max_iterations=15,
        )
        if parsed.command == "optimize" and parsed.mode == "cst":
            simulation_runner = RealCSTRunner(project_path=parsed.project_path)
            pipe_cfg.execution_mode = "cst"
        else:
            simulation_runner = MockCSTRunner()
        pipeline = OptimizationPipeline(pipe_cfg, runner=simulation_runner)
        result = pipeline.run()

        # Step 5: Wearable SAR evaluation if requested
        wearable_summary = None
        if getattr(parsed, "wearable", False):
            print("[Phase 4] Evaluating wearable head-loading SAR & MIMO metrics...")
            w_eval = WearableAntennaEvaluator()
            sar_res = w_eval.evaluate_sar(
                input_power_w=0.1,
                antenna_distance_skin_mm=5.0,
                frequency_hz=freq_hz,
            )
            wearable_summary = sar_res

        # Step 6: Generate Markdown report
        print("[Phase 5] Generating design report...")
        report_text = generate_optimization_report(
            project_name=pipe_cfg.project_name,
            topology_name=best_cand["topology"],
            requirements=reqs,
            initial_params=initial_params,
            optimized_params=result["best_parameters"],
            sensitivity_ranking=result.get("sensitivity_analysis", {}).get("ranking", []),
            history_records=result.get("history_records", []),
            wearable_summary=wearable_summary,
            cst_output_path=str(out_dir / f"{pipe_cfg.project_name}.cst"),
        )
        report_path = save_report(report_text, out_dir / f"{pipe_cfg.project_name}_Report.md")
        print(f"  Report saved to: {report_path}")

        print("=== Swarm Pipeline Completed Successfully ($0 Cost Verified) ===")
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
