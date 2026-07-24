from __future__ import annotations

from .common import resolved


def compile_solver(solver, parameters: dict[str, float]) -> str:
    solver_type = (
        "HF Time Domain" if solver.type == "time_domain" else "HF Frequency Domain"
    )
    return "\n".join(
        [
            f'Solver.FrequencyRange "{resolved(solver.frequency_min, parameters)}", "{resolved(solver.frequency_max, parameters)}"',
            f'ChangeSolverType "{solver_type}"',
        ]
    )
