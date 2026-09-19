# Testing

Run the complete offline verification:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m compileall -q src tests
.\.venv\Scripts\python.exe -m pip check
Get-ChildItem src\prompt2cst\qml\*.qml | ForEach-Object {
    .\.venv\Scripts\pyside6-qmllint.exe -I src\prompt2cst\qml $_.FullName
}
.\.venv\Scripts\python.exe -m pip wheel . --no-deps --wheel-dir outputs\package-audit
```

Offline tests cover all deterministic calculations, safe expressions,
DesignIR schemas, capability checks, dependency/geometry/material/port/
simulation validation, legacy adapters, Boolean and transform compilation,
compiler determinism, model fallback and structured-output rejection, batched
preview, approval hashing, plan tampering, progress persistence, and normalized
missing-result behavior. Swarm tests additionally cover role order, typed
handoffs, deterministic calculation ownership, persistent conversations,
revision invalidation, model provenance, denial without writes, and exact-plan
builds without another model call.

## Live CST testing

Live tests require Windows, CST Studio Suite 2026, COM registration, a valid
licence, and a controlled output directory. Inspect the History List and
geometry for every enabled compiler capability. Solver execution, mesh/licence
limits, sweeps, optimization, and result extraction require separate approval
and must not be claimed from offline mocks.

The offline suite mocks only the final CST execution boundary.

### Controlled parameter/response experiment

On a compatible CST 2026 installation, run the bounded two-point experiment:

```powershell
.\.venv\Scripts\python.exe -m prompt2cst.cli cst-dipole-link `
  --project-name controlled_dipole_link `
  --length-a-mm 55 --length-b-mm 65 --freq 2.45 --output-dir outputs
```

It creates a center-fed dipole whose arm ranges and discrete-port endpoints
reference CST's `dipole_length_mm` and `feed_gap_mm` parameters. It performs
two real `StoreParameter -> Rebuild -> Solver` runs, writes per-candidate ASCII
S11, Touchstone, raw-result JSON, and an evidence ledger. A zero exit status
means only that the two extracted resonances differed; it is not an impedance
optimization, a production-design result, or a compliance claim.
