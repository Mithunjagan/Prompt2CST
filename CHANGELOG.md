# Changelog

All notable Prompt2CST changes are documented here.

## Unreleased

- A fresh, single-prompt 868 MHz PIFA run automatically selected its length,
  ran five real openEMS solves, and passed the -10 dB S11, adjacent-mesh and
  enlarged-air-domain port checks. This is not far-field or hardware proof.

- Added an explicit PASS/FAIL/INCONCLUSIVE verdict scoped to simulated PIFA
  port checks; an unmet S11 target or failed mesh/domain comparison cannot be
  reported as a pass, and unchecked comparisons remain inconclusive.

- Clarified that hosted-model/OpenRouter access is optional for free local
  simulation, documented the official Windows openEMS/CSXCAD wheel setup for
  Python 3.11, and made setup report local-solver readiness separately.

- A real 868 MHz v4 PIFA candidate passed adjacent-mesh S11/impedance
  convergence and a controlled 25%-larger-air-domain comparison at 868 MHz.
  Far-field, 915 MHz, tolerance and physical tests remain unverified.

- Added a PIFA-only fabrication *proposal* to simulated runs: exact-plan-hash
  geometry dimensions, millimetre top/side SVG views, a BOM and explicit
  material/feed/tolerance unknowns. It is not a manufacturing-ready drawing
  or measured-performance certificate.

- Began a versioned PIFA conductor-edge mesh experiment following openEMS's
  1/3-metal, 2/3-air guidance. Recipe v3 was rejected after an unintended
  tiny cell prevented solver-energy convergence; v4 removes that cell and
  remains under real-solver mesh/domain validation. No antenna-performance
  claim is made from the experimental recipe.

- Defined separate, testable stop gates for a standalone 868/915 MHz PIFA
  milestone. Added quarter-wavelength PIFA air padding, a controlled
  air-domain convergence check, and bounded automatic recovery when mesh
  refinement loses the S11 target. Real openEMS follow-up runs also exposed
  a mesh-sensitive apparent match; reports retain that failed evidence rather
  than claiming success. Removed the repository's MIT license file, badge,
  and package license declaration at the project owner's request.

- Added deterministic openEMS project generators for PIFA, axial-mode helix,
  five-element Yagi-Uda, pyramidal horn, and exponential Vivaldi antennas.
  Each generator emits a strict canonical plan, inspectable executable Python,
  family-appropriate feed, optional NF2FF setup, result-extraction path, provenance, and
  explicit backend availability. Autonomous CLI and desktop workflows can
  generate these projects without an API key and never fabricate solver data.
  A bounded \`openems-run\` command rejects modified generated scripts and low-disk
  runs before launching the solver.
- Added prompt-to-FDTD execution in the CLI and desktop, a resumable PIFA
  length/feed search, and iterative mesh-convergence checks within the run
  budget, retaining the last completed result if a finer mesh times out. Solver results carry
  their exact project hash and reject nonfinite or mismatched sweeps. Fixed a
  shorted Yagi feed and a Vivaldi feed that missed its copper edges.
  Optional NF2FF runs now extract directivity, radiation efficiency, and
  realized gain after a completed solver run.
- Added a strict, cited antenna-family knowledge catalogue covering 13 core
  wire, planar, aperture, array, and reflector families. Architecture artifacts
  now include the selected family's sizing-rule IDs, limitations, source URLs,
  and honest CST implementation status; the catalogue is queryable locally
  through \`antenna-knowledge\`.
- Added safe, local ingestion of parameterized S11 sweep ZIP datasets with
  SHA-256 provenance, target-frequency suitability checks, one-factor
  sensitivity analysis, normalized artifacts, and autonomous-project evidence
  integration. Opaque geometry parameters cannot be promoted to manufacturing
  inputs without an explicit mapping.
- Added a zero-key **Autonomous Local** desktop workflow with optional dataset
  selection, background project generation, persisted history, explicit
  solver limitations, and direct review of the generated artifact paths.
- Quarantine CST Stage-B projects after native Save failures, extend bounded
  result-export timeouts, and drain large multiprocessing results before worker
  joins to avoid false COM timeouts and unsafe in-place resumes.

- Added DesignIR 1.0, safe expressions, deterministic RF calculations,
  capability validation, a modular CST compiler, legacy-family adapters,
  role-based provider routing, persistent workflow state, immutable preview
  hashes, batched MCP tools, operation-level execution progress, result
  provenance schemas, desktop model/capability browsers, acceptance/security
  tests, and complete architecture documentation.
- Added a comprehensive GitHub-ready README covering architecture, runtime
  flows, setup, outputs, tools, security, troubleshooting and every maintained
  repository file.
- Added a centered project hero, sanitized product screenshot, quick product
  journey, grouped component architecture, application state machine,
  trace-flow diagram, and realistic preview/build/denial Activity logs.
- Replaced the hard-coded `D:\Prompt2CST\outputs` default with a portable
  checkout-local output directory and a per-user installed fallback.
- Made setup stop on failed environment creation, installation or tests.
- Corrected the default 2.45 GHz monopole wire radius from 6.12 mm to 0.612 mm.
- Added a repository test for the editable-checkout output location.

## 0.5.0 beta 1

- Rebuilt the desktop shell in Qt Quick/QML.
- Added the liquid-glass RF workspace, rounded panels, motion and responsive
  status feedback.
- Added a custom CST approval sheet with explicit argument and preview review.
- Added Windows Mica/rounded-corner integration with a translucent fallback.
- Added one-command setup and double-click launchers.
- Added public-repository documentation, security guidance and Windows CI.
- Preserved the typed MCP safety boundary and existing CST automation backend.

## 0.4.0 beta 1

- Added a structured desktop workflow and antenna-family selector.
- Added center-fed dipole and validated custom-parametric builders.
- Expanded the local MCP server to 12 typed tools.
- Improved worker lifetime management, timeouts and error reporting.

## 0.3.0 beta 1

- Added verified cylindrical wire-monopole geometry.
- Added discrete-port, open-boundary and far-field-monitor generation.
- Added explicit preview-before-build enforcement.
