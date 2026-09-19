# Prompt2CST adversarial validation matrix

Initial audit date: 2026-09-13. Updated after blocker remediation and final Stage-A frequency-lock verification on 2026-09-14.
This is an evidence record, not a release sign-off. `PASS`
means the stated behavior was demonstrated in this audit; it does not mean a
real antenna design is validated.

## Current implementation verification

## Snapshot-integrity update — 2026-09-14

| Phase | Status | Evidence / limitation |
|---|---|---|
| CST snapshot integrity | GREEN | Unit coverage verifies CST-native SaveAs orchestration, unique target generation, busy-solver rejection, source protection, parameter readback, invalid-result detection, and PIFA integration. On 2026-09-14, `C:\p2cst\realval2_ac38b31d8135\realval2.cst` reopened after CST-native SaveAs, read back `feed_offset_mm=0.5`, and yielded real CST S11/Zin: resonance 2.0250001 GHz, S11 -16.473012 dB, Zin 45.1738-j13.5986 ohm. |
| Stage A PIFA resonance workflow | GREEN — FREQUENCY_LOCKED | The local refinement selected `radiator_length_mm=21.75` with `feed_offset_mm` frozen at `0.5` mm. The final real CST solve returned 1,001 S11 samples, exported ASCII and Touchstone data, and measured resonance `2.447` GHz (absolute error `3` MHz, within the `10` MHz tolerance); S11 was `-6.9916788` dB and Zin was `47.2139+j48.4932` ohm. CST read back both parameters before solving. The CST-native snapshot `C:\p2cst\local_refine_fbb2c1ceff1e\local_refined_final_project.cst` reopened, read back `radiator_length_mm=21.75` and `feed_offset_mm=0.5`, and contained extracted final results with S11/Touchstone artifacts. Checkpoint: `outputs/real_pifa_frequency_optimization/checkpoint.json`; no Stage B impedance-matching work was started. |

The validated Stage-A snapshot is `C:\p2cst\local_refine_fbb2c1ceff1e\local_refined_final_project.cst`; the repository checkpoint and final export evidence remain under `outputs/real_pifa_frequency_optimization/`. Stage B is intentionally not started by this verification.

On 2026-09-13, the complete offline suite ran with `126 passed`, `0 failed`.
Compilation, `pip check`, QML lint, and a no-dependency wheel build passed.
The CLI completed the smart-glasses YAML workflow in `mock` mode and wrote a
versioned artifact tree, a checkpoint, and a report labeled `MOCK_SIMULATION`.
A read-only connection check also connected to `CSTStudio.Application.2026`.
No new live solver run was performed in this verification; the existing
controlled-dipole CST artifacts remain the relevant real-solver evidence.

## Execution record

| Check | Result |
|---|---|
| Full unit suite | `104 passed`, `0 failed`, `0 skipped`; 12.31 s test runtime (14.84 s wall-clock command) |
| Suite warnings | No PDF parser is installed (`PyMuPDF` or `pdfminer.six`); staged optimizer reported empty active parameter sets in existing tests |
| `run-swarm --freq 2.45 --wearable` | Exited 0 in 1.3 s; chose dipole and wrote five files under `outputs/` |
| Requested `optimize examples/smart_glasses_2.45ghz.yaml --mode mock` | Failed: the CLI does not accept a spec path or `--mode` |
| Dependencies / static checks | `pip check` passed; Python compilation passed; QML lint passed |
| Real CST 2026 COM connection | Connected successfully to `CSTStudio.Application.2026` |
| Real CST creation run | The real CST application accepted and saved an `audit_dipole.cst` project with units, two arms, discrete port, solver configuration, boundaries, far-field monitor, and outputs |

## Post-fix revalidation

| Phase | Status | Current evidence / remaining limitation |
|---|---|---|
| 1 — real CST result extraction | GREEN | A solved CST 2026 dipole exported 1,001 S11 samples via the selected `1D Results/S-Parameters/S1,1` tree. Independent ASCII and Touchstone exports agreed at 2.000, 2.128, and 2.500 GHz within 0.000002 dB. Raw exports are retained in `outputs/test_dipole_td_raw_results.json`; Zin (68.54−j6.57 Ω) and VSWR (1.397) are calculated from CST complex S11 at the exported resonance, not fabricated. Direct CST Z-parameter-tree export remains intentionally unsupported. |
| 2 — real CST optimization path | YELLOW | `--mode cst` requires a `CST_SIMULATION` runner and rejects a mock runner. The real runner rejects unavailable outputs rather than using nominal values. A fresh bounded real two-candidate controlled-dipole run completed on 2026-09-13 and retained raw S11/Touchstone exports, but the general numerical pipeline has not yet been executed against it. |
| 3–4 — parameter-to-geometry and parameter-to-EM-response linkage | GREEN | On 2026-09-13, `controlled_dipole_link_20260913_tagged.cst` used CST expressions referencing `dipole_length_mm` in both arm ranges and port endpoints. Two real CST solves after `StoreParameter → Rebuild` produced 1,001-sample S11/Touchstone exports: 55.0 mm resonated at 2.3529799 GHz (S11 −15.501432 dB, Zin 68.88−j6.56 Ω) and 65.0 mm at 2.011205 GHz (S11 −15.44 dB, Zin 69.08−j6.51 Ω). Per-candidate raw artifacts and the evidence ledger are retained in `outputs/controlled_dipole_link_20260913_tagged_*`. |
| 5–6 — real numerical resonance/impedance/staged optimization | RED | The parameter/response link is physically demonstrated, and the pipeline now has stage-appropriate resonance/impedance objectives, but the general numerical optimizer has not yet run a real CST sweep with a measured resonance/impedance improvement. The controlled dipole has no demonstrated impedance-control parameter. |
| 7 — resumability | YELLOW | The pipeline now checkpoints each uncached candidate and a focused test proves it restores last parameters and skips a completed stage. An interrupted real CST run has not yet restored and continued a real stage. |
| 8 — concurrency safety | GREEN | `ProjectWorkspace.save_artifact` now uses an in-process lock, SQLite `BEGIN IMMEDIATE`, WAL/busy-timeout settings, and atomic file replacement. Five concurrent writes create versions 1–5 without overwrite. |
| 9 — zero-cost enforcement | GREEN | Remote OpenAI-compatible providers, including OpenRouter, are blocked at construction and immediately before requests in zero-cost mode; focused tests cover OpenAI, Anthropic, Gemini, and an arbitrary paid-cloud endpoint. Local deterministic/Ollama routing is unaffected. |
| 10–11 — literature provenance and paper-to-design | RED | Conflict detection is unit-tested, but PDF parsing and provenance-preserving architecture retrieval still require the remaining remediation. |
| 12 — smart-glasses CST pipeline | RED | The CLI now accepts a specification path and `--mode cst`, but correctly refuses to begin without a parameterized CST project path. No smart-glasses CST project or real optimization result exists. |
| 13 — reporting claims | YELLOW | Real runner results carry `CST_SIMULATION`; mock results retain `MOCK_SIMULATION`. End-to-end report consumption of typed real results is still incomplete. |
| 14 — acceptance tests | YELLOW | 126 tests pass, including artifact-backed dry-run/mock CLI workflows, parameterized dipole history linkage, `StoreParameter → Rebuild → Save` bridge behavior, candidate-level checkpoint restore, parser provenance, no-fallback result handling, cst-mode mock rejection, concurrency, and paid-provider blocking. Live optimization/resume acceptance tests remain missing. |

The historical matrix below records the original audit findings. Where it
conflicts with this post-fix table, the post-fix table is current.

## Validation matrix

| Feature | Implemented | Unit Tested | Integration Tested | Real CST Tested | Evidence Verified | Limitations | Confidence |
|---|---|---|---|---|---|---|---|
| Offline test suite | PASS | PASS | PARTIAL | NOT VERIFIED | PASS | Tests contain mock boundaries and do not demonstrate physical RF validity. | Medium |
| Mock swarm CLI | PARTIAL | PASS | PARTIAL | NOT VERIFIED | PASS | It succeeds but writes only `outputs/cache.db`, histories, sensitivity JSON, and report. It does not create the requested project artifact tree or named JSON deliverables. | High |
| Documented mock optimize command | FAIL | NOT VERIFIED | FAIL | NOT VERIFIED | PASS | CLI only accepts `--topology`, `--freq`, and `--output-dir`; no YAML input, `--mode`, or `resume` command exists. | High |
| Optimization resumability | PARTIAL | PARTIAL | FAIL | NOT VERIFIED | PASS | `ChiefOrchestrator.resume` reloads workspace metadata only. The optimizer has no persisted iteration/checkpoint restore; iteration 6 continuation and duplicate-simulation prevention were not possible to demonstrate. | High |
| Concurrent artifact safety | FAIL | NOT VERIFIED | FAIL | NOT VERIFIED | PASS | Two simultaneous `save_artifact` calls for the same id race on version 1; one produced `UNIQUE constraint failed: artifacts.artifact_id, artifacts.version`. No transaction, retry, or file-atomicity protocol protects it. | High |
| Zero-cost enforcement | FAIL | PARTIAL | FAIL | NOT VERIFIED | PASS | With `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, and `GEMINI_API_KEY` set, `audit-cost` reported zero violations and `run-swarm` completed. `orchestration.py` also contains an OpenAI-compatible HTTP client outside the guard. | High |
| Provider-neutral model router | PARTIAL | PASS | NOT VERIFIED | NOT VERIFIED | PASS | No Antigravity SDK/private endpoint/fake client was found in `model_router.py`; it only probes local Ollama. Its external state is `NEEDS_AGENT`, not the requested explicit `EXTERNAL_AGENT_EXECUTION_REQUIRED`. | Medium |
| PDF ingestion | FAIL | PARTIAL | FAIL | NOT VERIFIED | PASS | No parser dependency is installed. Regex extraction found frequency, S11, gain, bandwidth, and efficiency in supplied text, but not tables, equations, scientific notation, dimensions, ohms, or permittivity. Sections are always empty. | High |
| Literature claim provenance | FAIL | PARTIAL | FAIL | NOT VERIFIED | PASS | Extracted values are all labeled `literature_reported`; the extractor does not distinguish measured, simulated, or assumed. `add_paper_claims` collapses values into a parameter dictionary and discards unit/page/section/type. | High |
| Local RAG | PARTIAL | PARTIAL | PARTIAL | NOT VERIFIED | PASS | Manual chunks returned actual text, filename, page, and score; a targeted query ranked paper A first (0.7454). Chunks have no section field, duplicate/contradiction policy is absent, and TF word overlap is not evidence verification. | Medium |
| RF architecture selection | PARTIAL | PARTIAL | PARTIAL | NOT VERIFIED | PASS | Five synthetic requests yielded dipole/monopole rather than one topology, but application requirements are ignored. The 5.8 GHz slot request selected monopole; dual-band/MIMO requirements are not modeled. | High |
| Equation-driven sizing | PARTIAL | PASS | NOT VERIFIED | NOT VERIFIED | PASS | Patch, PIFA, IFA, monopole, dipole, and meander have topology-specific first-pass equations. Slot/loop/frame/transparent use a generic quarter-wave fallback, inappropriate as a general slot design equation. No loading, feed, substrate, body, coupling, or EM effects make dimensions CST-ready. | High |
| Parameter-role inference | PARTIAL | PASS | PARTIAL | NOT VERIFIED | PASS | There are topology maps followed by name heuristics. Metadata does not store role source (`explicit`, topology rule, sensitivity, or inferred), and sensitivity rank is not used by prioritization. | High |
| Finite-difference sensitivity | PARTIAL | PARTIAL | PARTIAL | NOT VERIFIED | PASS | A linear oracle produced correct central derivatives/signs (2, 3, -1, -4) with a 1-unit step. Bounds, units, and invalid perturbations are not handled; the compatibility wrapper hard-codes resonance and emits fabricated sensitivity fields. | High |
| Objectives and normalization | FAIL | PARTIAL | FAIL | NOT VERIFIED | PASS | Impedance errors were correct: 0, 10, 10, and 14.142 ohm for 50+j0, 60+j0, 50+j10, and 60+j10. `s11_from_impedance` has no return, so all four S11 values were `None`; VSWR is declared but not scored, and objective terms are not normalized across units. | High |
| Staged optimization | FAIL | PARTIAL | FAIL | NOT VERIFIED | PASS | The run stopped after stage A with cost 5.4 because it compares a cost to `abs(early_stop_s11_db)`. No stage-specific objective, preservation regression, or mandatory-constraint check prevents later stages from degrading earlier ones. | High |
| Adversarial / infeasible optimization | FAIL | NOT VERIFIED | FAIL | NOT VERIFIED | PASS | No feasibility model or `INFEASIBLE` terminal result exists. The mock swarm reports successful completion despite its initial poor S11 and mismatch. | High |
| Simulation cache | PARTIAL | PASS | PARTIAL | NOT VERIFIED | PASS | Identical parameters hit the cache and a 1e-6 change missed it. Solver label/settings are stored but excluded from the hash, so changing solver settings does not invalidate results. | High |
| CST geometry / port / setup | PARTIAL | PASS | PASS | PASS | PASS | The live 2026 COM server accepted the compiled dipole History operations and saved a project. This is a syntax/creation test, not an EM-result validation. | Medium |
| CST solver execution | PARTIAL | PASS | PARTIAL | PARTIAL | PARTIAL | Live COM inspection proved the real API is `OpenFile`, `Active3D()`, and `Solver()`, not `OpenDocument`. The code was corrected and the actual transient/post-processing solver processes were observed. A fresh end-to-end post-fix solve has not yet yielded extractable results. | Low |
| CST result extraction | PARTIAL | NOT VERIFIED | FAIL | NOT VERIFIED | FAIL | The extractor still uses unverified `OpenDocument`, samples only index 0, and has no curve/unit/interpolation/bandwidth logic. No live S11, VSWR, or impedance output was extracted. | High |
| CST optimizer VBA | PARTIAL | PARTIAL | NOT VERIFIED | NOT VERIFIED | FAIL | Script generation has unsupported result-path/method assumptions and no parameter-range compiler. It was not executed in CST; syntax and goals are not validated against CST 2026. | High |
| Wearable / SAR | PARTIAL | PASS | PARTIAL | NOT VERIFIED | PARTIAL | Tissue values cite a comment but lack source, model/measurement basis, temperature, and per-record provenance. SAR is a capped scalar heuristic, not 1 g/10 g field averaging. Report wording was corrected to `ASSUMED`/`CALCULATED` estimate and explicitly not a compliance determination. | High |
| MIMO metrics | FAIL | NOT VERIFIED | FAIL | NOT VERIFIED | FAIL | `MIMOIsolation` is a data container; there is no S11/S22/S21/S12 extraction, S21/S12 isolation calculation, or valid ECC computation. | High |
| Final report provenance | PARTIAL | PASS | PARTIAL | NOT VERIFIED | PASS | The report now labels calculated and mock outputs and says SAR is not a compliance determination. It still cannot represent measured/literature/CST data end-to-end because those sources are not preserved. | Medium |
| Performance telemetry | PARTIAL | PARTIAL | PARTIAL | NOT VERIFIED | PASS | Suite and mock runtime were measured. Simulation count/cache stats exist, but research time, memory, cache-hit rate, and DB-size reporting are incomplete. | Medium |
| Backward compatibility | PARTIAL | PASS | PARTIAL | PARTIAL | PASS | 104 offline tests, compile, dependency check, and QML lint pass. Live GUI/MCP use and full CST result flow remain unverified. | Medium |

## Required artifact check

The command produced these actual files in `outputs/`:

- `cache.db`
- `optimization_history.json`
- `optimization_history.csv`
- `sensitivity_report.json`
- `Swarm_dipole_2450MHz_Report.md`

It did **not** produce the requested `project/`, `requirements/`, `research/`,
`architecture/`, `design/`, `simulations/`, `optimization/`, and `final/`
tree, nor `requirements.json`, `evidence.json`,
`candidate_architectures.json`, `selected_architecture.json`, `design_ir.json`,
`parameters.json`, `final_parameters.json`, or `final_report.md`.

## Final verdict

### GREEN — actually validated

- The Python offline suite currently passes: 104 tests, zero failures.
- CST Studio Suite 2026 COM connectivity was real, not mocked.
- The live CST application accepted the generated dipole creation operations:
  geometry, discrete port, solver setup, boundaries, monitor, and project save.
- The report no longer calls the heuristic SAR value FCC compliant; it marks
  it as an estimate and not a compliance determination.

### YELLOW — works only under mock/unit assumptions

- Deterministic mock swarm execution, topology scoring, closed-form starter
  sizing, finite-difference central-difference core, basic local chunk search,
  and parameter hashing.
- The creation-side CST compiler has one demonstrated real-CST path, but no
  real RF outputs have been validated.

### RED — unverified, unreliable, or incorrect

- Cost guard, documented optimize CLI, optimization resumption, concurrent
  artifact persistence, paper ingestion/provenance, and real-CST extraction.
- Objective S11 computation and multi-objective normalization.
- Stage progression/regression protection and infeasibility reporting.
- MIMO/SAR regulatory claims and CST optimizer VBA execution.

## Five highest-priority engineering fixes

1. Make zero-cost enforcement a mandatory boundary: reject configured paid
   keys before every provider construction/call, remove or gate the
   OpenAI-compatible path, and add process-level tests proving calls cannot
   leave the process.
2. Repair optimizer correctness before tuning: restore the S11 return value,
   implement/validate VSWR, normalize objective terms, use stage-specific
   objectives, and enforce earlier-stage and mandatory-constraint regressions.
3. Make workspace persistence transactional: lock/version artifact writes,
   atomically write JSON, persist optimizer iteration/cache identity, expose a
   real CLI resume command, and prove interrupted iteration 5 resumes at 6.
4. Build a provenance-preserving research pipeline: include a local PDF
   parser, retain source/page/section/unit/type for every value, distinguish
   measured/simulated/assumed claims, and make RAG return those fields without
   merging contradictory papers.
5. Finish real CST verification: use only type-library-confirmed COM APIs in
   solver and extraction, obtain full sampled curves with units, derive
   resonance/bandwidth from real data, execute optimizer VBA in CST, and keep
   every real-CST test artifact and error trace.
