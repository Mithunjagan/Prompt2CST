from __future__ import annotations

FAMILY_OPTIONS = [
    (
        "Auto detect",
        "auto",
        "Let the model choose from the safe antenna catalog.",
    ),
    (
        "Wire monopole · verified",
        "wire_monopole",
        "Cylindrical monopole, PEC ground, discrete port and far-field monitor.",
    ),
    (
        "Center-fed dipole · beta",
        "center_fed_dipole",
        "Two cylindrical arms separated by a discrete center-feed port.",
    ),
    (
        "Rectangular patch · geometry beta",
        "rectangular_patch",
        "Analytical inset-fed patch geometry; excitation is not complete.",
    ),
    (
        "Custom parametric · beta",
        "custom_parametric",
        "Safe composition of bricks, cylinders, dielectrics and discrete ports.",
    ),
]


EXAMPLE_PROMPTS = {
    "auto": (
        "Design a 2.45 GHz center-fed dipole with a 50 ohm discrete port, "
        "a 2 to 3 GHz sweep, open boundaries and a far-field monitor."
    ),
    "wire_monopole": (
        "Design a 2.45 GHz vertical wire monopole with length 30.6 mm, "
        "radius 0.612 mm, a 61.2 mm square ground plane, a 1.5 mm feed gap "
        "and a 50 ohm discrete port. Use a 2 to 3 GHz sweep."
    ),
    "center_fed_dipole": (
        "Design a 2.45 GHz center-fed cylindrical dipole with 61.2 mm total "
        "conductor length, 0.5 mm radius, a 1.5 mm center gap and a 50 ohm "
        "discrete port. Use a 2 to 3 GHz sweep."
    ),
    "rectangular_patch": (
        "Design a 2.45 GHz inset-fed rectangular patch on FR-4 with relative "
        "permittivity 4.3, loss tangent 0.02 and 1.6 mm substrate thickness."
    ),
    "custom_parametric": (
        "Create a 2.45 GHz rectangular-loop antenna from four PEC bricks, "
        "with a small center feed gap and a 50 ohm discrete port. Keep every "
        "coordinate within 100 mm and use open boundaries."
    ),
}


def compose_user_request(
    prompt: str,
    family_id: str,
    mode: str,
) -> str:
    cleaned = prompt.strip()
    if not cleaned:
        raise ValueError("Enter an antenna request")
    if mode not in {"preview", "build"}:
        raise ValueError("mode must be preview or build")

    family_hint = (
        "Choose the correct supported antenna family from the capability catalog."
        if family_id == "auto"
        else f"Requested antenna family: {family_id}."
    )
    action = (
        "Preview only. Do not build, write to CST or run a solver."
        if mode == "preview"
        else (
            "Build the validated preview in CST. Do not run a solver. "
            "The desktop must still request interactive approval before "
            "any CST-writing tool executes."
        )
    )
    return f"{cleaned}\n\n{family_hint}\n{action}"
