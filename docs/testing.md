# Testing

Run the complete offline verification:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m compileall -q src tests
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\pyside6-qmllint.exe -I src\prompt2cst\qml src\prompt2cst\qml\*.qml
.\.venv\Scripts\python.exe -m pip wheel . --no-deps --wheel-dir outputs\package-audit
```

Offline tests cover all deterministic calculations, safe expressions,
DesignIR schemas, capability checks, dependency/geometry/material/port/
simulation validation, legacy adapters, Boolean and transform compilation,
compiler determinism, model fallback and structured-output rejection, batched
preview, approval hashing, plan tampering, progress persistence, and normalized
missing-result behavior.

## Live CST testing

Live tests require Windows, CST Studio Suite 2026, COM registration, a valid
licence, and a controlled output directory. Inspect the History List and
geometry for every enabled compiler capability. Solver execution, mesh/licence
limits, sweeps, optimization, and result extraction require separate approval
and must not be claimed from offline mocks.

The offline suite mocks only the final CST execution boundary.
