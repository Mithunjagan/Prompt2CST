# Contributing

Prompt2CST accepts focused fixes, tests, documentation, DesignIR capabilities,
validators, deterministic compiler modules and antenna templates.

## Local development

1. Use Windows with Python 3.11.
2. Run `setup.bat`.
3. Run the offline test suite:

   ```powershell
   .\.venv\Scripts\python.exe -m unittest discover -s tests -v
   ```

4. Launch with `Prompt2CST.bat`.

Most geometry and validation tests do not require CST. A real CST 2026 machine
is required before declaring a new macro verified.

## Adding a capability or antenna template

- Prefer a template adapter into DesignIR over a new execution path.
- Register the exact primitive/operation/port/simulation capability.
- Add deterministic calculations and validation where required.
- Confirm exact CST 2026 syntax before enabling a compiler capability.
- Keep preview free of CST writes and require immutable-hash approval.
- Add valid, invalid, boundary, deterministic-output and injection tests.
- Inspect the generated project and History List inside CST 2026.

Never add a general code-execution tool for LLM-generated Python, VBA, shell
commands or CST macros. Do not add solver/optimization execution without a
separate preview, approval, duration and licence/mesh-budget design.
