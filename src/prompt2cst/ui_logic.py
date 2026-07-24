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

PHASE_OPTIONS = [
    (
        "Requirements",
        "requirements",
        "Parse intent, constraints, topology and missing details.",
    ),
    (
        "Calculations",
        "calculations",
        "Calculate RF dimensions, assumptions and first-pass formulas.",
    ),
    (
        "Parameters",
        "parameters",
        "Resolve named CST parameters, ranges and units.",
    ),
    (
        "Modeling",
        "modeling",
        "Plan geometry, materials, feed objects and operations.",
    ),
    (
        "Simulation",
        "simulation",
        "Plan boundaries, solver, sweeps, mesh and monitors.",
    ),
    (
        "Validation",
        "validation",
        "Critique the plan before any CST write is possible.",
    ),
    (
        "Preview",
        "preview",
        "Compile a non-writing DesignIR/CST operation preview.",
    ),
]

PHASE_TO_ROLE = {
    "requirements": "requirements_model",
    "calculations": "calculations_model",
    "parameters": "parameters_model",
    "modeling": "geometry_model",
    "simulation": "simulation_model",
    "validation": "critic_model",
    "preview": "swarm_coordinator",
    "build": "deterministic_executor",
}

PHASE_INSTRUCTIONS = {
    "requirements": (
        "Run only the requirements phase. Extract the requested antenna goal, "
        "frequency, materials, feed, solver needs and missing information. "
        "Do not build or write to CST."
    ),
    "calculations": (
        "Run only the calculations phase. Use deterministic RF formulas and "
        "show assumptions, units and derived dimensions. Do not build or write "
        "to CST."
    ),
    "parameters": (
        "Run only the parameter-setting phase. Produce named CST parameters, "
        "safe ranges and unit choices. Do not build or write to CST."
    ),
    "modeling": (
        "Run only the modeling phase. Plan geometry, materials, booleans, "
        "ports and named objects in a reviewable way. Do not build or write "
        "to CST."
    ),
    "simulation": (
        "Run only the simulation-planning phase. Define solver, boundaries, "
        "sweeps, mesh and monitors, but do not run the solver or write to CST."
    ),
    "validation": (
        "Run only the validation phase. Find blocking issues, unsupported "
        "capabilities and risky assumptions before preview/build."
    ),
    "preview": (
        "Run the preview phase. Validate and compile a non-writing preview "
        "that the user can inspect before build."
    ),
    "build": (
        "Run the build phase only from an acceptable validated preview. The "
        "desktop must still request interactive approval before any CST write."
    ),
}


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
    phase: str = "preview",
) -> str:
    cleaned = prompt.strip()
    if not cleaned:
        raise ValueError("Enter an antenna request")
    if mode not in {"preview", "build"}:
        raise ValueError("mode must be preview or build")
    if phase not in PHASE_INSTRUCTIONS:
        raise ValueError("unknown execution phase")
    if mode == "build" and phase != "build":
        phase = "build"

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
    return f"{cleaned}\n\n{family_hint}\n{PHASE_INSTRUCTIONS[phase]}\n{action}"


def compose_swarm_request(prompt: str, family_id: str) -> str:
    cleaned = prompt.strip()
    if not cleaned:
        raise ValueError("Enter an antenna request")
    family_hint = (
        "Requested antenna family: auto detect."
        if family_id == "auto"
        else f"Requested antenna family: {family_id}."
    )
    return f"{cleaned}\n\n{family_hint}"


def role_for_phase(phase: str) -> str:
    if phase not in PHASE_TO_ROLE:
        raise ValueError("unknown execution phase")
    return PHASE_TO_ROLE[phase]
