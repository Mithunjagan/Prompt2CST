# Autonomous antenna machine: bounded delivery goals

The full-stop milestone is deliberately narrower than "any antenna": from one
natural-language request for an **868 or 915 MHz PIFA**, the installed local
app must autonomously produce a reproducible, optimized openEMS design, pass
numerical checks, and save a fabrication-oriented package and honest report.
No Codex session, hosted model, paid API, manual dimension retuning, or CST
license may be required at runtime. A physical-performance claim still requires
a measured prototype. Adding more antenna families is a later goal, not a
substitute for finishing this one.

Progress is recorded against the gates below. A goal is **done** only when its
acceptance checks pass in an automated test and, where indicated, a saved real
solver run. A generated script or synthetic/mock result cannot satisfy a live
solver gate. Failed, timed-out, or budget-exhausted jobs must report that state
rather than silently claiming success.

## Goal 0 — Preserve a reproducible baseline

**Deliverable:** a cleanly versioned local-solver path, documented 868 MHz
pilot evidence, and a repeatable test command. **Stop when:** the complete
offline suite, compilation, package/dependency checks, and UI lint pass; the
pilot report identifies which numbers came from actual openEMS output and
which checks remain outstanding. **Current state:** partially complete; the
868 MHz pilot exists, but its domain and far-field are not converged.

## Goal 1 — Make one PIFA solve numerically credible

**Deliverable:** a validated simulation domain with adequate radiator-to-PML
clearance, plus automated mesh **and domain-size** convergence checks for
S11/impedance. Add far-field convergence for gain, efficiency, and pattern,
with explicit thresholds and saved comparison files. **Stop when:** real
openEMS runs at both 868 and 915 MHz meet their requested S11 targets and
the comparisons pass, or the app records a clear non-passing outcome. Neither
a single mesh nor a single NF2FF run qualifies. The current PIFA air-box
clearance is only about 40 mm in places, so the earlier 868 MHz pilot is
provisional until this gate is met.

## Goal 2 — Close the optimization loop

**Deliverable:** bounded, resumable optimization of PIFA length and feed,
including automatic retuning when a finer mesh or larger domain invalidates
the apparent winner. Search candidates are identified by plan hash and cache
only matching, validated results. **Stop when:** a prompt can start from the
untuned default at 868 and 915 MHz and reach a passing Goal 1 candidate
without a person choosing new dimensions; tests also cover timeout, restart,
budget exhaustion, and an initially matched candidate that fails refinement.
The existing coarse PIFA search is a starting point, not completion of this
goal.

## Goal 3 — Produce a buildable *proposal*, not a fake certificate

**Deliverable:** dimensioned radiator/ground/short/feed drawings or CAD,
units, coordinate datum, material and connector assumptions, a bill of
materials, tolerances, and machine-readable solver provenance. **Stop when:**
the package can be regenerated from the winning immutable plan, key dimensions
match that exact simulated geometry, and the report labels idealized versus
fabrication/measurement unknowns. A physical claim remains **unverified**
until a prototype is measured.

## Goal 4 — Run it as a standalone local product

**Deliverable:** desktop/CLI submission of the same request, visible progress,
bounded CPU/time/disk use, checkpoint/resume, cancellation, and a final
pass/fail/inconclusive report with artifact links. **Stop when:** a fresh
Windows installation with documented free dependencies can complete the
868/915 MHz workflow by launching Prompt2CST, without opening Codex or
ChatGPT. The local language model is optional for interpreting wording; it
must not fabricate electromagnetic results or override deterministic checks.

## Goal 5 — End-to-end acceptance and measured feedback

**Deliverable:** repeatable real-solver acceptance runs for 868 and 915 MHz,
then at least one fabricated prototype with calibrated VNA/Touchstone input
and a documented simulation-versus-measurement comparison. **Stop when:** the
software gates are green, the physical discrepancy is reported rather than
hidden, and the measured evidence is traceable to the exact design revision.
Until hardware is tested, the product may say *simulation-validated design
proposal*, never *measured practical antenna*.

## After the full stop: expand family coverage

Each new family gets its **own** geometry, feed, mesh/domain/far-field checks,
optimizer, fabrication output, reference benchmark, and acceptance run. The
existing helix, Yagi-Uda, horn, and Vivaldi generators are not automatically
validated products. Unsupported requests must fail explicitly. "Any antenna"
means an expanding tested library, not a promise that arbitrary geometry will
work from one prompt.

## Verification commands

Run from the repository root with the project environment installed:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m compileall -q src tests
.\.venv\Scripts\python.exe -m pip check
Get-ChildItem src\prompt2cst\qml -Filter *.qml | ForEach-Object { .\.venv\Scripts\pyside6-qmllint.exe -I src\prompt2cst\qml $_.FullName }
```

These are **offline** checks. Goals 1, 2, and 5 additionally require saved
real openEMS logs/results; Goal 5 additionally requires actual hardware data.
