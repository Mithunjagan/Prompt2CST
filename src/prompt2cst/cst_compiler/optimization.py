from __future__ import annotations

from typing import Any


def compile_optimization(goal: Any) -> str:
    """Compile an OptimizationGoal into CST VBA History script.

    Generates Optimizer VBA commands for CST Studio Suite 2026
    supporting S11, VSWR, gain, and efficiency optimization goals.

    Parameters
    ----------
    goal:
        An ``OptimizationGoal`` instance from ``design_ir.py``.
    """
    metric = str(goal.metric)
    operator = str(goal.operator)
    target = goal.target
    frequency = goal.frequency

    lines = ['With Optimizer']

    # Metric → CST result template mapping
    metric_map = {
        "s11_db": ("1D Results\\S-Parameters\\S1,1", "dB"),
        "vswr": ("1D Results\\VSWR\\VSWR(1)", ""),
        "gain_dbi": ("Farfield\\farfield (f={freq})\\Abs(Gain)", "dBi"),
        "efficiency": ("Farfield\\farfield (f={freq})\\Radiation Efficiency", ""),
    }

    if metric not in metric_map:
        lines.append(f'  \' WARNING: unsupported metric "{metric}"')
        lines.append('End With')
        return "\n".join(lines)

    result_template, unit = metric_map[metric]
    if frequency is not None:
        result_template = result_template.replace("{freq}", str(frequency))
    else:
        result_template = result_template.replace("{freq}", "2.45")

    # Operator mapping
    operator_map = {
        "minimize": "Min",
        "maximize": "Max",
        "lte": "<=",
        "gte": ">=",
    }
    cst_operator = operator_map.get(operator, "Min")

    # Build goal specification
    if operator in ("minimize", "maximize"):
        lines.append(f'  .SetGoalOperator "{cst_operator}"')
        lines.append(f'  .SetGoalTarget ""')
    else:
        lines.append(f'  .SetGoalOperator "{cst_operator}"')
        if target is not None:
            lines.append(f'  .SetGoalTarget "{target}"')

    lines.append(f'  .SetGoalResultName "{result_template}"')

    if unit:
        lines.append(f'  .SetGoalUnit "{unit}"')

    # Frequency constraint
    if frequency is not None:
        lines.append(f'  .SetGoalRangeType "Single"')
        lines.append(f'  .SetGoalRange1 "{frequency}"')
    else:
        lines.append(f'  .SetGoalRangeType "Total"')

    # Add the goal
    lines.append(f'  .AddGoal')

    # Constraints
    for constraint in goal.constraints:
        lines.append(f'  \' Constraint: {constraint}')

    lines.append('End With')
    return "\n".join(lines)
