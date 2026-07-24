# Prompt2CST contributor instructions

## Architecture

Prompt2CST is a Python 3.11 Windows desktop application. PySide6/QML is the
frontend, `Prompt2CSTController` is the desktop boundary, OpenRouter-compatible
model providers perform structured planning, and the local FastMCP server
exposes batched design-plan tools. `DesignIR` is the single typed interchange
format between planning, deterministic validation, the CST compiler, preview,
approval, execution, and result extraction. CST writes use Windows COM and CST
History List commands through `CSTBridge`.

Legacy antenna-family inputs must be adapted into DesignIR; do not create a
second unvalidated execution path.

## Coding conventions

- Target Python 3.11 and Pydantic v2.
- Use strict schemas with unknown fields rejected.
- Keep RF arithmetic in deterministic modules, not prompts.
- Keep compiler output stable for identical canonical DesignIR.
- Return explicit unsupported-capability errors; never substitute topology.
- Preserve the current QML visual identity and keep controller logic testable.
- Add focused `unittest` coverage with every behavior change.

## Development commands

```powershell
.\setup.bat
.\.venv\Scripts\python.exe -m prompt2cst.gui
.\.venv\Scripts\python.exe -m prompt2cst.server
```

## Testing commands

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m compileall -q src tests
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\pyside6-qmllint.exe -I src\prompt2cst\qml src\prompt2cst\qml\*.qml
```

## Security rules

- Treat model output as untrusted and validate it before use.
- Never expose provider keys in frontend persistence, logs, errors, generated
  plans, CST files, or tracked configuration.
- Never execute model-produced shell, Python, JavaScript, raw VBA, COM, paths,
  or macros.
- Only the deterministic compiler may create executable CST operations.
- Preview is read-only. Execution requires an immutable stored plan, explicit
  human approval, and an exact SHA-256 content-hash match.
- Redact secrets before logging and confine outputs below configured roots.

## CST automation rules

- CST Studio Suite 2026 is the supported live target.
- Reuse History List syntax proven in this repository.
- Each operation has a deterministic label and command block.
- Never call `Solver.Start` during preview.
- Execute approved plans in a new project and stop at the exact failed
  operation. Do not report a partially written project as successful.
- Mock only the external CST/COM boundary in offline tests.

## Definition of done

A change is done only when schemas, capabilities, validation, compiler,
preview/approval behavior, tests, and documentation agree. Run the complete
offline suite, Python compilation, dependency checks, QML lint, and packaging
checks. State clearly when live CST, solver, licence, model credentials, or
external result verification remains outstanding.
