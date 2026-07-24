from __future__ import annotations


def compile_boundaries(boundary) -> str:
    value = {
        "open": "open",
        "expanded_open": "expanded open",
        "electric": "electric",
        "magnetic": "magnetic",
        "periodic": "periodic",
    }
    return f"""
With Boundary
    .Xmin "{value[boundary.xmin]}"
    .Xmax "{value[boundary.xmax]}"
    .Ymin "{value[boundary.ymin]}"
    .Ymax "{value[boundary.ymax]}"
    .Zmin "{value[boundary.zmin]}"
    .Zmax "{value[boundary.zmax]}"
    .ApplyInAllDirections "False"
End With
""".strip()
