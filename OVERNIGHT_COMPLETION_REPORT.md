# Overnight completion report

Date: 2026-09-13

## Completed work

- Added atomic candidate-level checkpointing to `OptimizationPipeline`.
- Resume now restores the last parameters, skips completed stages, and relies on the persistent, runner-specific cache to avoid repeating completed candidates.
- Stage A now scores resonance-frequency error; stage B scores complex input-impedance error.
- Added a focused automated resume test.

## Tests

- `./.venv/Scripts/python.exe -m unittest discover -s tests -q`: 126 passed.
- `./.venv/Scripts/python.exe -m compileall -q src tests`: passed.
- `./.venv/Scripts/python.exe -m pip check`: passed.

## Real CST experiment

Command executed:

```powershell
.\.venv\Scripts\python.exe -m prompt2cst cst-dipole-link --project-name overnight_controlled_dipole_20260913 --length-a-mm 55 --length-b-mm 65 --freq 2.45 --output-dir outputs
```

This created and solved a fresh parameterized CST project. CST updated, rebuilt, solved, and exported 1,001 S11 samples plus Touchstone data for each candidate.

| Dipole length | Real CST resonance | S11 at resonance | Derived Zin |
|---:|---:|---:|---:|
| 55.0 mm | 2.3529799 GHz | -15.501432 dB | 68.8768 - j6.5600 ohm |
| 65.0 mm | 2.0112050 GHz | -15.439006 dB | 69.0825 - j6.5104 ohm |

The changed resonance is real CST evidence of parameter-to-geometry-to-response linkage. It is not evidence of a successful numerical optimization, impedance matching, staged optimization, or real resume.

## Artifacts

- `outputs/overnight_controlled_dipole_20260913.cst`
- `outputs/overnight_controlled_dipole_20260913_parameter_response_link.json`
- Per-candidate raw JSON, ASCII S11, and Touchstone exports under `outputs/` with the same prefix.
- `.agent_state/current_state.json` and `.agent_state/progress.md`

## Known limitations and blockers

- No real numerical optimization sweep has been run with measured improvement.
- The controlled dipole only has a demonstrated resonance parameter; it does not provide a demonstrated impedance-control parameter for real matching.
- No interrupted real CST optimization has yet been resumed.
- No compact smart-glasses PIFA/IFA CST model exists, so its real simulation and optimization remain RED.
- The general `--mode cst` flow requires a CST project whose named parameters match the generated design parameters.

## Exact next action

Create a CST model with both a verified resonance parameter and a verified feed/matching parameter, then run it through the real runner with a small staged candidate budget. For the current controlled model, inspect its status with:

```powershell
.\.venv\Scripts\python.exe -m prompt2cst resume project
```

For the live evidence project, begin from `outputs/overnight_controlled_dipole_20260913.cst`; do not relabel its two-point response-link evidence as optimization.

## Snapshot-integrity update (2026-09-14)

- The prior `initial_project.cst` / `final_project.cst` archives remain untrusted. They were not overwritten, repaired, or deleted.
- `CSTBridge.create_validated_cst_snapshot` now uses CST-native `Save` then `SaveAs` at a unique short path under `C:\p2cst`, reopens the result, checks exact requested parameters, and optionally extracts S11/Zin. Failure is explicit as `SNAPSHOT_INVALID` and evidence is retained.
- Offline verification: 133 tests, compilation, and `pip check` passed. The snapshot-specific tests include busy-solver protection, source protection, parameter readback, missing-result detection, and PIFA resume integration.
- A real validation attempt against `outputs/real_pifa_impedance_optimization/working_project.cst` exposed CST's maximum-path-length dialog for the earlier nested target. It is **not** a snapshot success or archive validation. The source remains the known-good live project; the short-path fix still needs one real reopen/readback proof.
