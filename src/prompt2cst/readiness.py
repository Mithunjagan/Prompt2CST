"""Read-only, user-facing checks for local Prompt2CST workflows."""

from __future__ import annotations

import platform
import subprocess
import sys
from typing import Any

from .cst_bridge import CSTBridge, default_output_dir
from .openems_backend import backend_status


def readiness_report() -> dict[str, Any]:
    """Describe what this installation can do without starting a solver or CST."""

    system = platform.system()
    display_system = "macOS" if system == "Darwin" else system
    python_supported = sys.version_info[:2] == (3, 11)
    binding_issue = ""
    try:
        solver = backend_status()
    except Exception as exc:
        solver = {
            "available": False,
            "executable": None,
            "python_modules": {"openEMS": False, "CSXCAD": False},
        }
        binding_issue = f"Solver discovery failed: {type(exc).__name__}."
    bindings_importable = False
    if solver["available"]:
        try:
            probe = subprocess.run(
                [sys.executable, "-c", "import CSXCAD, openEMS"],
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )
            bindings_importable = probe.returncode == 0
            if not bindings_importable:
                binding_issue = "Python bindings are installed but cannot be imported."
        except (OSError, subprocess.TimeoutExpired):
            binding_issue = "Python binding import check did not complete."

    if system == "Windows":
        try:
            cst = CSTBridge().status(test_connection=False)
            cst_registered = bool(cst.get("registered"))
        except (OSError, RuntimeError):
            cst_registered = False
    else:
        cst_registered = False

    simulate_ready = bool(
        python_supported and solver["available"] and bindings_importable
    )
    steps: list[str] = []
    if not python_supported:
        steps.append("Install CPython 3.11 and rerun setup.")
    if not solver["available"]:
        steps.append(
            "Install openEMS, CSXCAD Python bindings and the native solver "
            "using the platform-specific README instructions."
        )
    elif not bindings_importable:
        steps.append(
            "Repair the openEMS/CSXCAD native library path and Python bindings "
            "in this virtual environment."
        )
    if system != "Windows":
        steps.append(
            "CST COM builds require Windows; local planning and openEMS remain separate."
        )
    elif not cst_registered:
        steps.append(
            "CST 2026 is optional; install/register it only for approved CST builds."
        )

    return {
        "platform": display_system,
        "python": platform.python_version(),
        "python_supported": python_supported,
        "output_dir": str(default_output_dir()),
        "modes": {
            "plan": python_supported,
            "openems_generate": python_supported,
            "openems_simulate": simulate_ready,
        },
        "openems": {
            "status": "READY" if simulate_ready else "NEEDS_SETUP",
            "executable": solver["executable"],
            "python_modules": solver["python_modules"],
            "bindings_importable": bindings_importable,
            "issue": binding_issue,
        },
        "cst": {
            "status": "REGISTERED" if cst_registered else "UNAVAILABLE",
            "connection_tested": False,
            "note": "Registration is not a live CST/license check.",
        },
        "next_steps": steps,
    }


def format_readiness(report: dict[str, Any]) -> str:
    """Render a compact checklist suitable for both CLI and desktop UI."""

    modes = report["modes"]

    def mark(ready: bool) -> str:
        return "READY" if ready else "NEEDS SETUP"

    lines = [
        f"Platform: {report['platform']} | Python: {report['python']}",
        f"Local planning: {mark(modes['plan'])}",
        f"openEMS geometry generation: {mark(modes['openems_generate'])}",
        f"openEMS simulation: {mark(modes['openems_simulate'])}",
        f"CST integration: {report['cst']['status']} "
        "(Windows only; live connection and licence not tested)",
        f"Output directory: {report['output_dir']}",
    ]
    issue = report["openems"]["issue"]
    if issue:
        lines.append(f"Solver issue: {issue}")
    if report["next_steps"]:
        lines.append("Next steps:")
        lines.extend(f"  - {step}" for step in report["next_steps"])
    return "\n".join(lines)
