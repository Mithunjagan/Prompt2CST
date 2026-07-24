# Security

## API keys

Prompt2CST keeps the OpenRouter key in memory for the current app session. Do
not commit keys, place them in screenshots, paste them into issues, or add them
to prompts. The repository ignores `.env` and `*.key` files as a precaution.

If a key is exposed, revoke it immediately in OpenRouter and create a new one.

## Model and DesignIR boundary

Model responses are untrusted and must validate against strict Pydantic
schemas. Design expressions use a restricted arithmetic parser; model output
cannot execute Python, JavaScript, shell commands, file access, network access,
COM statements, or raw CST macros. Provider credentials remain in backend
process memory or approved environment configuration and are redacted from
orchestration logs.

## CST write boundary

The model can call only the typed local MCP tools. It cannot execute arbitrary
Python, PowerShell or VBA through Prompt2CST. Every CST-writing tool requires:

1. a calculated read-only preview;
2. an immutable stored plan and SHA-256 content hash;
3. a visible approval sheet containing the arguments and exact preview;
4. explicit user approval with the matching hash.

Projects are saved under the configured Prompt2CST output directory. Batched
execution creates a new project, records each operation, and saves after the
sequence completes. Solver execution and live result extraction remain
unavailable; missing results are reported explicitly and are never invented.

See [docs/security.md](docs/security.md) for the complete threat model.

## Reporting a vulnerability

Do not publish active credentials or an unsafe proof of concept in a public
issue. Open a private security advisory in the repository and include the
version, reproduction steps and expected impact.
