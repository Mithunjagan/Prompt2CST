# Contributing

Prompt2CST accepts focused fixes, tests, documentation and new validated
antenna families.

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

## Adding an antenna family

- Add a typed preview tool and a separate typed build tool.
- Validate dimensions, frequency ranges, materials, names and primitive limits.
- Keep preview generation free of CST writes.
- Require `confirm=true` only after the desktop approval flow.
- Add unit tests for valid, invalid and boundary inputs.
- Inspect the generated project and History List inside CST 2026.
- Document whether the family is verified, beta or geometry-only.

Never add a general code-execution tool for LLM-generated Python, VBA, shell
commands or CST macros. Do not add solver execution without a separate safety
and Learning Edition mesh-budget design.
