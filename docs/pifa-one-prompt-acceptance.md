# One-prompt PIFA port acceptance: 868 and 915 MHz

These were two separate fresh local runs of `prompt2cst design`, each starting
from one natural-language request with `--mode openems-simulate
--max-iterations 15`. Neither run supplied a tuned length or feed position.
The local deterministic search found the geometry, real openEMS FDTD produced
the port data, and the workflow checked a finer mesh and a 25%-larger air
domain before writing its report and geometry/BOM proposal.

| Band | Real solves | Auto-selected length scale / feed fraction | Final S11 at target | Mesh ΔS11 / ΔZ | Air-domain ΔS11 / ΔZ | Port gate |
|---|---:|---|---:|---|---|---|
| 868 MHz | 5 | 1.4375 / 0.10 | −12.54 dB | 0.209 dB / 7.27 Ω | 0.112 dB / 1.44 Ω | PASS |
| 915 MHz | 5 | 1.4370 / 0.10 | −13.24 dB | 0.276 dB / 6.07 Ω | 0.052 dB / 1.20 Ω | PASS |

The programmed acceptance limits are S11 ≤ −10 dB at the target frequency,
adjacent-mesh and enlarged-domain changes each ≤ 1 dB in S11 and ≤ 10 Ω in
complex impedance. Both solver logs reached the −40 dB energy-decay stop
criterion. `PASS` here means **simulated port criteria only**, never a
fabricated antenna or measured radiation performance.

## Reproduce the two prompt runs

With compatible free openEMS and CSXCAD installed, run from the repository root:

```powershell
.\.venv\Scripts\python.exe -m prompt2cst design "Design a practical 868 MHz PIFA antenna with S11 below -10 dB" --mode openems-simulate --max-iterations 15 --project-dir D:\Prompt2CST-LocalAI\acceptance\pifa-868-prompt-v4
.\.venv\Scripts\python.exe -m prompt2cst design "Design a practical 915 MHz PIFA antenna with S11 below -10 dB" --mode openems-simulate --max-iterations 15 --project-dir D:\Prompt2CST-LocalAI\acceptance\pifa-915-prompt-v4
```

Use a different output directory if that drive is unavailable. The exact
candidate plan SHA-256 values in these runs were
`01723dd8bb15283578e18814b4733229c0281222364ebe2c295e4e4e764111b3`
at 868 MHz and
`9f8fb1a59c95cbeb97c9b6fed2f15d3f23ca913e81a208b77b27f2b278183273`
at 915 MHz. The raw `results.json`, `solver.log`, `mesh_convergence.json`,
`domain_convergence.json`, final report and fabrication proposal remain in
each local output directory. The 868 MHz run preceded the explicit
`port_verdict` field but its saved validation independently records the
target and both checks as passed; the 915 MHz validation reports
`port_verdict: PASS`.

## Not yet a practical-antenna certificate

The model uses zero-thickness ideal PEC sheets and a lumped 50 Ω port. It
does not yet model conductor thickness/loss, a real connector transition,
support dielectric, enclosure, nearby objects or build tolerances. No
near-field-to-far-field convergence, gain, radiation efficiency, pattern,
fabricated sample or calibrated VNA measurement was supplied. The generated
SVG/BOM files are traceable geometry proposals, not manufacturing-ready
instructions. Those checks remain separate acceptance gates in
[the roadmap](autonomous-antenna-goals.md).
