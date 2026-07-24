from __future__ import annotations

from .common import format_number


def compile_mesh(mesh) -> str:
    if mesh.local_refinements:
        raise ValueError("Unsupported compiler capability: mesh.local_refinement")
    return f"""
With Mesh
    .LinesPerWavelength "{format_number(mesh.lines_per_wavelength)}"
End With
""".strip()
