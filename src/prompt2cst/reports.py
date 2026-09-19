"""Report generation for optimization runs and zero-cost RF swarm results.

Generates comprehensive Markdown reports summarizing requirements, candidate topolgies,
sensitivity analysis, optimization convergence history, wearable SAR metrics, and CST outputs.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def generate_optimization_report(
    project_name: str,
    topology_name: str,
    requirements: dict[str, Any],
    initial_params: dict[str, float],
    optimized_params: dict[str, float],
    sensitivity_ranking: list[dict[str, Any]] | None = None,
    history_records: list[dict[str, Any]] | None = None,
    wearable_summary: dict[str, Any] | None = None,
    cst_output_path: str | None = None,
) -> str:
    """Generate a full markdown optimization report."""
    lines = []
    lines.append(f"# Prompt2CST RF Swarm Design Report: {project_name}")
    lines.append("")
    lines.append("## Executive Summary")
    lines.append(f"- **Project Name:** `{project_name}`")
    lines.append(f"- **Selected Topology:** `{topology_name}`")
    lines.append(f"- **Target Frequency:** `{requirements.get('center_frequency_hz', 2.45e9) / 1e9:.3f} GHz` (`{requirements.get('frequency_min_hz', 2.4e9)/1e9:.3f}` to `{requirements.get('frequency_max_hz', 2.5e9)/1e9:.3f}` GHz)")
    lines.append(f"- **Target Impedance:** `{requirements.get('target_impedance_ohm', 50.0)} Ω`")
    if cst_output_path:
        lines.append(f"- **CST Model Output:** `{cst_output_path}`")
    lines.append("")

    lines.append("## Optimization Results")
    lines.append("| Parameter | Initial Value (mm) | Optimized Value (mm) | Delta (mm) | Provenance |")
    lines.append("|---|---|---|---|---|")
    all_keys = sorted(set(initial_params.keys()) | set(optimized_params.keys()))
    for k in all_keys:
        v_init = initial_params.get(k, 0.0)
        v_opt = optimized_params.get(k, v_init)
        delta = v_opt - v_init
        lines.append(
            f"| `{k}` | {v_init:.3f} | {v_opt:.3f} | {delta:+.3f} | "
            "Initial: `CALCULATED`; optimized: `MOCK_SIMULATION` |"
        )
    lines.append("")

    if sensitivity_ranking:
        lines.append("## Parameter Sensitivity Ranking")
        lines.append("| Rank | Parameter | Resonant Freq Sens (GHz/mm) | Re(Zin) Sens (Ω/mm) | Im(Zin) Sens (Ω/mm) |")
        lines.append("|---|---|---|---|---|")
        for r in sensitivity_ranking:
            lines.append(
                f"| {r.get('rank', 0)} | `{r.get('parameter')}` | "
                f"{r.get('f0_sens', 0.0):.4f} | {r.get('re_z_sens', 0.0):.4f} | "
                f"{r.get('im_z_sens', 0.0):.4f} |"
            )
        lines.append("")

    if history_records:
        lines.append("## Optimization Convergence")
        lines.append("All convergence values below are `MOCK_SIMULATION`, not CST results.")
        lines.append(f"Total Iterations: {len(history_records)}")
        lines.append("")
        lines.append("| Iteration | Stage | S11 (dB) | Re(Zin) (Ω) | Im(Zin) (Ω) | Objective Cost |")
        lines.append("|---|---|---|---|---|---|")
        for rec in history_records[:20]:  # Cap at top 20 for readability
            res = rec.get("results", {})
            cost = rec.get("cost", 0.0)
            stage = rec.get("stage", "main")
            iteration = rec.get("iteration", 0)
            s11 = res.get("s11_db", 0.0)
            re_z = res.get("zin_re", 50.0)
            im_z = res.get("zin_im", 0.0)
            lines.append(f"| {iteration} | {stage} | {s11:.2f} | {re_z:.2f} | {im_z:.2f} | {cost:.4f} |")
        lines.append("")

    if wearable_summary:
        lines.append("## Wearable & SAR Estimate")
        lines.append(
            "The values below are `ASSUMED`/`CALCULATED` screening estimates, "
            "not a regulatory SAR simulation or compliance determination."
        )
        lines.append(f"- **Tissue Model:** `{wearable_summary.get('tissue_model', '4-Layer Head')}`")
        lines.append(f"- **Max 1g SAR:** `{wearable_summary.get('sar_1g_w_kg', 0.0):.3f} W/kg` (FCC Limit: {wearable_summary.get('fcc_limit', 1.6)} W/kg)")
        lines.append("- **Threshold comparison:** `NOT A COMPLIANCE DETERMINATION`")
        lines.append("")

    lines.append("## Provenance & System Traceability")
    lines.append("- Optimization engine: Deterministic SciPy Differential Evolution / Sweep")
    lines.append("- Model cost: $0.00 / ₹0.00")
    lines.append("- Codebase: Prompt2CST Zero-Cost RF Swarm")
    lines.append("")

    return "\n".join(lines)


def save_report(report_text: str, output_path: str | Path) -> Path:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(report_text, encoding="utf-8")
    return path
