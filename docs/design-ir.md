# DesignIR 1.0

`prompt2cst.design_ir.DesignIR` is the strict, versioned interchange format.
Unknown fields are rejected by Pydantic. Every material, geometry item,
operation, port, monitor, sweep, and optimization goal has a stable ID.

DesignIR contains project metadata, units, named parameters, materials,
geometry, operations, excitations, boundaries, solver and mesh configuration,
monitors, sweeps, optimization goals, requested outputs, dependencies,
traceability, and warnings.

The schema represents bricks, cylinders, spheres, cones, sheet rectangles,
polygons, polygon extrusions, polylines, curves, and imported references.
Representation does not imply compilation support; the capability registry is
the source of truth. Currently verified compiler coverage is deliberately
narrower.

## Safe expressions

Dimensions may be numbers or restricted arithmetic expressions. The parser
accepts named parameters, numeric constants, parentheses, `+ - * / % **`,
`pi`, `e`, and the allow-listed `sqrt`, `sin`, `cos`, `tan`, `abs`, `min`, and
`max` functions.

Attributes, comprehensions, imports, file access, shell calls, Python/JS/COM
access, and unknown functions or names are rejected. Parameters are resolved
deterministically and cycles are blocking errors.

## Extending DesignIR

1. Add a strict discriminated Pydantic model.
2. Register its capability.
3. Add deterministic validation and bounding behavior.
4. Add a compiler only after confirming CST 2026 syntax.
5. Add valid, invalid, deterministic-snapshot, and live-CST tests.
