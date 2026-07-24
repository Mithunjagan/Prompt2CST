from __future__ import annotations

from ..design_ir import Material, MaterialKind
from .common import format_number, history_string


def compile_material(material: Material) -> str:
    name = history_string(material.id)
    if material.kind == MaterialKind.PEC:
        return ""
    if material.kind == MaterialKind.DIELECTRIC:
        return f"""
With Material
    .Reset
    .Name "{name}"
    .Folder ""
    .FrqType "all"
    .Type "Normal"
    .SetMaterialUnit "GHz", "mm"
    .Epsilon "{format_number(material.relative_permittivity or 1)}"
    .Mue "1"
    .TanD "{format_number(material.loss_tangent or 0)}"
    .TanDGiven "True"
    .Create
End With
""".strip()
    return f"""
With Material
    .Reset
    .Name "{name}"
    .Folder ""
    .FrqType "all"
    .Type "Normal"
    .SetMaterialUnit "GHz", "mm"
    .Epsilon "1"
    .Mue "1"
    .Kappa "{format_number(material.conductivity_s_per_m or 0)}"
    .Create
End With
""".strip()
