from __future__ import annotations

from .common import history_string, resolved


def compile_monitor(monitor, parameters: dict[str, float]) -> str:
    field_type = {
        "farfield": "Farfield",
        "surface_current": "Surfacecurrent",
        "efield": "Efield",
        "hfield": "Hfield",
    }[monitor.type]
    return f"""
With Monitor
    .Reset
    .Name "{history_string(monitor.id)}"
    .Dimension "Volume"
    .Domain "Frequency"
    .FieldType "{field_type}"
    .Frequency "{resolved(monitor.frequency, parameters)}"
    .UseSubvolume "False"
    .Create
End With
""".strip()
