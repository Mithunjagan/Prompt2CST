# Security

## API keys

Prompt2CST keeps the OpenRouter key in memory for the current app session. Do
not commit keys, place them in screenshots, paste them into issues, or add them
to prompts. The repository ignores `.env` and `*.key` files as a precaution.

If a key is exposed, revoke it immediately in OpenRouter and create a new one.

## CST write boundary

The model can call only the typed local MCP tools. It cannot execute arbitrary
Python, PowerShell or VBA through Prompt2CST. Every CST-writing tool requires:

1. a calculated read-only preview;
2. a visible approval sheet containing the arguments and preview;
3. explicit user approval.

Projects are saved under the configured Prompt2CST output directory. Solver
execution and result extraction are intentionally unavailable in this beta.

## Reporting a vulnerability

Do not publish active credentials or an unsafe proof of concept in a public
issue. Open a private security advisory in the repository and include the
version, reproduction steps and expected impact.
