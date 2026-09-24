"""Traceable PIFA geometry proposal, not a manufacturing certificate."""

from __future__ import annotations

import csv
import json
import math
from pathlib import Path

from .openems_backend import OpenEMSProject, pifa_dimensions


def write_pifa_fabrication_proposal(
    project: OpenEMSProject, output_dir: str | Path
) -> dict[str, str]:
    """Draw the exact simulated PEC geometry and list unresolved build choices.

    The drawings have millimetre coordinates and an explicit datum. They are
    proposals only: conductor thickness, supports, connector and tolerances
    are not part of this idealized EM model.
    """
    dimensions = pifa_dimensions(project)
    if any(not math.isfinite(value) or value <= 0 for value in dimensions.values()):
        raise ValueError("PIFA fabrication dimensions must be finite and positive")
    parts = {part.name: part for part in project.primitives}
    ground, radiator, short = (parts[name] for name in ("ground", "radiator", "short"))
    if any(part.kind != "box" or part.start is None or part.stop is None
           for part in (ground, radiator, short)):
        raise ValueError("PIFA proposal needs box ground, radiator and short")
    if not (radiator.start[0] <= project.port.start[0] <= radiator.stop[0]
            and radiator.start[1] <= project.port.start[1] <= radiator.stop[1]):
        raise ValueError("PIFA feed must lie within the radiator footprint")

    root = Path(output_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    top_path = root / "pifa_top_view.svg"
    side_path = root / "pifa_side_view.svg"
    manifest_path = root / "fabrication_proposal.json"
    bom_path = root / "bill_of_materials.csv"

    x0, x1 = ground.start[0], ground.stop[0]
    y0, y1 = ground.start[1], ground.stop[1]
    padding = 12.0
    width = x1 - x0 + 2 * padding
    height = y1 - y0 + 2 * padding + 24

    def tx(x: float) -> float:
        return x - x0 + padding

    def ty(y: float) -> float:
        return y1 - y + padding

    def top_rect(part, fill: str, opacity: float) -> str:
        return (
            f'<rect x="{tx(part.start[0]):.4f}" y="{ty(part.stop[1]):.4f}" '
            f'width="{part.stop[0]-part.start[0]:.4f}" '
            f'height="{part.stop[1]-part.start[1]:.4f}" '
            f'fill="{fill}" fill-opacity="{opacity}" stroke="#233a5e" '
            'stroke-width="0.35"/>'
        )

    top_path.write_text(
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width:.4f}mm" '
        f'height="{height:.4f}mm" viewBox="0 0 {width:.4f} {height:.4f}">\n'
        '<rect width="100%" height="100%" fill="white"/>\n'
        f'{top_rect(ground, "#b8c7d9", 0.7)}\n'
        f'{top_rect(radiator, "#df8f3b", 0.85)}\n'
        f'{top_rect(short, "#555e6b", 0.95)}\n'
        f'<circle cx="{tx(project.port.start[0]):.4f}" '
        f'cy="{ty(project.port.start[1]):.4f}" r="1.2" fill="#c92335"/>\n'
        f'<text x="{padding:.4f}" y="{height-19:.4f}" font-size="2.5" fill="#111" font-family="Arial">'
        f'Ground {dimensions["ground_length_mm"]:.2f} x '
        f'{dimensions["ground_width_mm"]:.2f} mm</text>\n'
        f'<text x="{padding:.4f}" y="{height-14:.4f}" font-size="2.5" fill="#111" font-family="Arial">'
        f'Radiator {dimensions["radiator_length_mm"]:.2f} x '
        f'{dimensions["radiator_width_mm"]:.2f} mm</text>\n'
        f'<text x="{padding:.4f}" y="{height-9:.4f}" font-size="2.5" fill="#111" font-family="Arial">'
        f'Feed {dimensions["feed_distance_from_short_edge_mm"]:.2f} mm '
        'from short edge; red dot marks location.</text>\n'
        f'<text x="{padding:.4f}" y="{height-4:.4f}" font-size="2.5" fill="#111" font-family="Arial">'
        'XY datum: ground centre. Ideal PEC; not a cut file.</text>\n'
        '</svg>\n',
        encoding="utf-8",
    )

    side_height = dimensions["radiator_height_mm"] + 38
    z_ground = side_height - 12
    z_radiator = z_ground - dimensions["radiator_height_mm"]
    side_path.write_text(
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width:.4f}mm" '
        f'height="{side_height:.4f}mm" viewBox="0 0 {width:.4f} {side_height:.4f}">\n'
        '<rect width="100%" height="100%" fill="white"/>\n'
        f'<line x1="{tx(ground.start[0]):.4f}" y1="{z_ground:.4f}" '
        f'x2="{tx(ground.stop[0]):.4f}" y2="{z_ground:.4f}" '
        'stroke="#667f9e" stroke-width="0.8"/>\n'
        f'<line x1="{tx(radiator.start[0]):.4f}" y1="{z_radiator:.4f}" '
        f'x2="{tx(radiator.stop[0]):.4f}" y2="{z_radiator:.4f}" '
        'stroke="#df8f3b" stroke-width="0.8"/>\n'
        f'<rect x="{tx(short.start[0]):.4f}" y="{z_radiator:.4f}" '
        f'width="{short.stop[0]-short.start[0]:.4f}" '
        f'height="{dimensions["radiator_height_mm"]:.4f}" fill="#555e6b"/>\n'
        f'<line x1="{tx(project.port.start[0]):.4f}" y1="{z_ground:.4f}" '
        f'x2="{tx(project.port.start[0]):.4f}" y2="{z_radiator:.4f}" '
        'stroke="#c92335" stroke-width="0.55" stroke-dasharray="1,1"/>\n'
        f'<text x="{padding:.4f}" y="{side_height-9:.4f}" font-size="2.5" fill="#111" font-family="Arial">'
        f'XZ at y=0; ground z=0; radiator z={dimensions["radiator_height_mm"]:.2f} mm.</text>\n'
        f'<text x="{padding:.4f}" y="{side_height-4:.4f}" font-size="2.5" fill="#111" font-family="Arial">'
        'Dashed feed is an ideal 50 ohm lumped port, not a connector.</text>\n'
        '</svg>\n',
        encoding="utf-8",
    )

    bom = [
        ("ground conductor", "1", "copper sheet proposed; thickness and conductivity not modeled"),
        ("radiator conductor", "1", "copper sheet proposed; thickness and conductivity not modeled"),
        ("short connection", "1", "conductive wall proposed; joint resistance not modeled"),
        ("feed and connector", "1", "physical 50 ohm connector and transition not selected or modeled"),
        ("mechanical support", "as needed", "dielectric material, permittivity and mounting not selected or modeled"),
    ]
    with bom_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(("item", "quantity", "proposal_and_model_limit"))
        writer.writerows(bom)

    manifest = {
        "status": "GEOMETRY_PROPOSAL_NOT_FABRICATION_VALIDATED",
        "source": "EXACT_OPENEMS_PLAN_GEOMETRY",
        "project_sha256": project.canonical_sha256,
        "units": "mm",
        "datum": "ground centre at x=0, y=0; ground plane z=0",
        "dimensions_mm": dimensions,
        "feed_xyz_mm": project.port.start,
        "solver_material_idealization": "zero-thickness perfect electric conductor",
        "proposed_unverified_tolerances_mm": {
            "planar_cut": 0.2,
            "radiator_height": 0.2,
            "feed_location": 0.1,
        },
        "unresolved_before_manufacture": [
            "Choose conductor thickness and verify finite-conductivity model",
            "Choose and model physical connector and feed transition",
            "Choose support material and model its permittivity and mounting",
            "Sweep the proposed dimensional tolerances in EM simulation",
            "Validate RF response on a calibrated physical prototype",
        ],
        "drawings": [top_path.name, side_path.name],
        "bill_of_materials": bom_path.name,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return {
        "fabrication_proposal": str(manifest_path),
        "fabrication_top_view": str(top_path),
        "fabrication_side_view": str(side_path),
        "fabrication_bom": str(bom_path),
    }
