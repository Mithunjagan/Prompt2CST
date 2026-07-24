# Deterministic CST compiler

`prompt2cst.cst_compiler` converts validated DesignIR into an ordered tuple of
labelled CST History List operations. Identical DesignIR produces identical
normalized history.

Modules separate parameters, materials, primitives, booleans, transforms,
ports, boundaries, solvers, mesh, monitors, sweeps, optimization, and output
metadata. Verified legacy syntax is reused for units, materials, bricks,
cylinders, discrete ports, frequency ranges, boundaries, and monitors.

Boolean compilation uses `Solid.Add`, `Solid.Subtract`, and `Solid.Intersect`.
Transform compilation supports translate, rotate, mirror, scale, duplicate,
linear array, rename, and delete. CST 2026 inspection is still required for
the transform and sweep command variants on the target installation.

Unsupported primitives fail capability validation before compilation. The
compiler never accepts raw VBA, COM statements, Python, JavaScript, or shell
content and never emits `Solver.Start`.

## Adding a primitive or Boolean operation

1. Confirm exact CST 2026 History List syntax in a controlled project.
2. Add schema and deterministic geometry validation.
3. Add or enable the capability registry entry.
4. Add the compiler function and deterministic fixture/snapshot.
5. Run offline tests and inspect the generated History List in CST 2026.
