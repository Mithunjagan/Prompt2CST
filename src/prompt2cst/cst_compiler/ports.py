from __future__ import annotations

from ..design_ir import Excitation
from .common import format_number, history_string, resolved


def compile_port(port: Excitation, parameters: dict[str, float], number: int) -> str:
    if port.type != "discrete_port":
        raise ValueError("Unsupported port compiler: port.waveguide")
    return f"""
With DiscretePort
    .Reset
    .PortNumber "{number}"
    .Type "SParameter"
    .Label "{history_string(port.name)}"
    .Impedance "{format_number(port.impedance_ohm)}"
    .Voltage "1.0"
    .Current "1.0"
    .SetP1 "False", "{resolved(port.p1[0], parameters)}", "{resolved(port.p1[1], parameters)}", "{resolved(port.p1[2], parameters)}"
    .SetP2 "False", "{resolved(port.p2[0], parameters)}", "{resolved(port.p2[1], parameters)}", "{resolved(port.p2[2], parameters)}"
    .InvertDirection "False"
    .LocalCoordinates "False"
    .Monitor "True"
    .Create
End With
""".strip()
