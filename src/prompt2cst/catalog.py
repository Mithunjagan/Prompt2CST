from __future__ import annotations


ANTENNA_FAMILIES = [
    {
        "id": "wire_monopole",
        "name": "Wire monopole",
        "status": "verified_on_cst_2026",
        "tool_pair": [
            "preview_wire_monopole",
            "build_wire_monopole",
        ],
        "features": [
            "PEC ground plane",
            "cylindrical radiator",
            "discrete port",
            "open boundaries",
            "far-field monitor",
        ],
    },
    {
        "id": "center_fed_dipole",
        "name": "Center-fed dipole",
        "status": "beta",
        "tool_pair": [
            "preview_center_fed_dipole",
            "build_center_fed_dipole",
        ],
        "features": [
            "two cylindrical PEC arms",
            "discrete center-feed port",
            "open boundaries",
            "far-field monitor",
        ],
    },
    {
        "id": "rectangular_patch",
        "name": "Inset-fed rectangular patch",
        "status": "geometry_beta",
        "tool_pair": [
            "preview_rectangular_patch",
            "build_rectangular_patch",
        ],
        "features": [
            "analytical first-pass dimensions",
            "custom dielectric substrate",
            "PEC patch and ground geometry",
        ],
        "limitations": [
            "excitation port is not implemented",
            "solver-ready validation is not complete",
        ],
    },
    {
        "id": "custom_parametric",
        "name": "Custom parametric antenna",
        "status": "beta",
        "tool_pair": [
            "preview_parametric_antenna",
            "build_parametric_antenna",
        ],
        "features": [
            "up to 64 validated bricks or cylinders",
            "PEC and user-defined dielectric materials",
            "up to four discrete ports",
            "open boundaries",
            "optional far-field monitor",
        ],
        "limitations": [
            "no arbitrary Python or VBA",
            "no booleans, rotations, curves, helix, torus or polygon extrusion",
            "no waveguide ports or phased excitations",
        ],
    },
]


UNSUPPORTED_CAPABILITIES = [
    "solver execution and automatic result extraction",
    "mesh-cell count guarantee",
    "waveguide ports",
    "phased-array excitation",
    "boolean geometry operations",
    "curves, helices, toroids and polygon extrusion",
    "automatic electromagnetic optimization",
]


def capability_catalog() -> dict:
    return {
        "families": ANTENNA_FAMILIES,
        "validated_primitives": [
            "brick",
            "axis-aligned cylinder",
            "normal dielectric material",
            "discrete port",
            "expanded-open boundary",
            "frequency-domain far-field monitor",
        ],
        "unsupported_capabilities": UNSUPPORTED_CAPABILITIES,
        "solver_run": False,
        "guidance": (
            "Use a dedicated family tool when one exists. Use the custom "
            "parametric tool only when the antenna can be represented with "
            "the validated primitives. Otherwise report the missing "
            "capability instead of substituting another antenna."
        ),
    }
