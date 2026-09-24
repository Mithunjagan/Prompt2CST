# Live openEMS 868 MHz PIFA pilot (2026-09-24)

This is a local **openEMS v0.0.36 FDTD result**, not a CST run, a faculty-dataset fit, or a physical measurement. The model uses ideal PEC metal, air, a 50 Ω ideal lumped feed, and an unenclosed finite ground plane. The target was S11 ≤ −10 dB at 868 MHz. Every numerical result below comes from a saved `results.json` and solver log under `D:\Prompt2CST-LocalAI\real-em\`.

## What the solver found

| Geometry and mesh | S11 at 868 MHz | Outcome |
| --- | ---: | --- |
| Initial PIFA, 1.0× mesh | −0.025 dB | Unmatched |
| Tuned length scale 1.4146, feed fraction 0.10, 1.0× mesh | −14.91 dB | Target met on this mesh only |
| Same geometry, 1.5× mesh | −7.58 dB | **Not converged**; changed by 7.33 dB and 62.0 Ω |
| Retuned length scale 1.4248, feed fraction 0.10, 1.5× mesh | −15.12 dB | Target met |
| Same retuned geometry, 1.8× mesh | −14.38 dB | **Converged by configured port criteria**: ΔS11 0.74 dB ≤ 1 dB and ΔZ 9.10 Ω ≤ 10 Ω |

The 1.8× port-only run gives approximately 71.24 − j9.36 Ω at 868 MHz. Its sampled −10 dB interval is 865.57–873.56 MHz, about 8.0 MHz or 0.92% of the center frequency. These are sampled bounds, not interpolated crossing frequencies. The solver energy decayed past −40 dB in the accepted runs.

The retuned idealized geometry has a 78.74 × 31.08 mm top radiator, 6.91 mm height, 98.74 × 51.08 mm ground, 1.0 mm short wall along x, and a feed 7.87 mm from the shorted radiator edge. The feed has 6.87 mm clearance from the end of the short wall. These are **simulation dimensions**, not a fabrication drawing; conductor thickness, connector, support, enclosure, and assembly tolerances are unspecified.

At 1.8× mesh with NF2FF recording, the solver reported S11 −14.21 dB, directivity 1.98 dBi, radiation efficiency 94.7%, and realized gain 1.57 dBi at 868 MHz. Its port response differs from the 1.8× port-only run by 0.17 dB and 1.10 Ω. The NF2FF box changes the mesh, and these **far-field values have not been independently mesh-convergence-tested**. The radiation-efficiency figure is for ideal PEC/air, so it is not a prediction of assembled hardware efficiency.

## Saved evidence

- Initial run and log: `D:\Prompt2CST-LocalAI\real-em\pifa-868-fastmesh-20260924\`
- Nine-point broad feed/length grid, all unmatched: `D:\Prompt2CST-LocalAI\real-em\pifa-868-search-20260924\search_summary.json`
- Near-short feed retune and failed first mesh check: `D:\Prompt2CST-LocalAI\real-em\pifa-868-feed-tune-20260924\`
- Retuned converged port result: `D:\Prompt2CST-LocalAI\real-em\pifa-868-refined-retune-20260924\mesh_convergence.json`
- Preliminary far-field result: `D:\Prompt2CST-LocalAI\real-em\pifa-868-farfield-20260924\results.json`

The backend now preserves `solver.log` on timeout/failure, rejects a run without −40 dB energy decay or a fresh result file, and includes a solver-recipe version in the plan hash. A wider Gaussian excitation and a less wasteful air-box mesh made the sub-GHz run practical; the requested frequency samples remain separate from excitation width. The matching workflow still requires mesh checks after tuning. These choices follow the [openEMS Python patch tutorial](https://docs.openems.de/en/latest/python/openEMS/Tutorials/Simple_Patch_Antenna.html) and [mesh guidance](https://docs.openems.de/en/latest/concepts/mesh.html); the [NF2FF documentation](https://docs.openems.de/en/latest/concepts/nf2ff.html) describes the far-field quantities.

## Follow-up air-domain check (2026-09-24)

The PIFA generator now places the PML at least one quarter-wavelength from
the geometry at the lowest sweep frequency. The earlier tuned dimensions,
rerun in this larger box at 1.5× mesh, yielded **S11 −4.99 dB at 868 MHz**;
their best sampled dip moved to 858.28 MHz. Thus the old matched geometry is
**not** accepted as a validated 868 MHz design. This new solver result is saved
under `D:\Prompt2CST-LocalAI\real-em\pifa-868-domain-qw-20260924\`.

The first box-enlargement attempt inadvertently changed the mesh step as well
as the boundary distance, so its apparent 2.65 dB difference was not a clean
domain test. The checker now fixes the effective maximum mesh step. With that
correction, another 25% increase in air padding changed S11 only **0.094 dB**
and impedance **0.41 Ω**, passing the configured port-domain thresholds.
The same quarter-wavelength box, compared at 1.5× and 1.875× mesh, changed
S11 by **0.43 dB** and impedance by **1.97 Ω**; that port-level mesh check
also passed. Both checks concern an **unmatched** geometry (refined S11
−5.43 dB at 868 MHz). Retuning, far-field convergence, and physical
construction remain open gates. See `mesh_convergence.json` and
`domain_convergence.json` alongside the saved solver inputs and logs.

A bounded real-FDTD retune in the same quarter-wavelength box found length
scale 1.4 and feed fraction 0.10, with S11 **−10.44 dB** at 868 MHz on the
1.5× mesh. Its 1.875× mesh result was **−9.64 dB**: the port comparison
itself converged (ΔS11 0.80 dB, ΔZ 4.96 Ω), but the requested match was
lost. The search and check are saved under
`D:\Prompt2CST-LocalAI\real-em\pifa-868-domain-search-v1\`. A refined-mesh
retune is therefore required; the 1.4 candidate is **not accepted**.

At 1.875× mesh, a resonance-guided real-solver retune increased length scale
to **1.4078** and reached S11 **−16.97 dB** at 868 MHz. But its 2.344× mesh
check returned **−9.56 dB**, changing by **7.40 dB** and **46.56 Ω**. That
comparison is **not converged**, and the apparent match is again rejected.
The two-stage retune and failing check are saved under
`D:\Prompt2CST-LocalAI\real-em\pifa-868-refined-search-v1\`. These results
show why the final gate cannot be defined as "one solver run below −10 dB."

## Remaining gates before a build claim

1. Repeat far-field at another mesh density and compare gain, efficiency, and pattern.
2. Sweep radiator/feed/short dimensions and manufacturing tolerances; the matched band is narrow.
3. Model real conductors, dielectric/support, feed/connector, enclosure, and nearby objects.
4. Make and measure a prototype with a calibrated VNA and radiation-pattern setup. No physical prototype was tested here.

This pilot validates one 868 MHz PIFA workflow; it does **not** establish that arbitrary prompted antenna families are solver-validated or manufacturable.
