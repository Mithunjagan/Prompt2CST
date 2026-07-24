from __future__ import annotations

from .common import format_number, history_string


def compile_sweep(sweep) -> str:
    if sweep.strategy == "explicit":
        values = ",".join(format_number(value) for value in sweep.values)
        return f'ParameterSweep.AddSequence "{history_string(sweep.parameter)}", "{values}"'
    return (
        f'ParameterSweep.AddLinear "{history_string(sweep.parameter)}", '
        f'"{format_number(sweep.start)}", "{format_number(sweep.stop)}", '
        f'"{format_number(sweep.step)}"'
    )
