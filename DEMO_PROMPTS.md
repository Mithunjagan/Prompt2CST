# Demo prompts

Start with **Preview design**. Build only after the dimensions and tool log are
correct.

## Wire monopole

```text
Preview a 2.45 GHz vertical cylindrical wire monopole with length 30.6 mm,
radius 0.612 mm, a 61.2 mm by 61.2 mm ground plane with 0.5 mm thickness,
a 1.5 mm feed gap, a 50 ohm discrete port and a 2 to 3 GHz frequency sweep.
Do not build it and do not run the solver.
```

## Center-fed dipole

```text
Preview a 2.45 GHz center-fed cylindrical dipole with 61.2 mm total conductor
length, 0.5 mm wire radius, a 1.5 mm center gap, a 50 ohm discrete port and a
2 to 3 GHz sweep. Do not run the solver.
```

## Rectangular patch

```text
Preview a 2.45 GHz inset-fed rectangular microstrip patch on FR-4 with relative
permittivity 4.3, loss tangent 0.02 and substrate thickness 1.6 mm. Do not
build it.
```

## Custom parametric geometry

```text
Preview a custom 3 GHz antenna using only validated axis-aligned bricks and
cylinders. Use PEC conductors, expanded-open boundaries and one 50 ohm
discrete port. List every primitive and coordinate before any CST write.
```

The custom builder supports only its declared primitives. Curves, helices,
rotations, polygon extrusion, boolean geometry, waveguide ports, arrays and
solver execution are not yet available.
