# Model orchestration

Seven roles are configurable independently:

- requirements
- RF reasoning
- geometry
- simulation
- critic
- code review
- results analysis

`ModelProvider` defines structured generation. The repository includes an
OpenAI-compatible provider (used for OpenRouter and compatible endpoints), a
mock provider, per-role routing, fallbacks, bounded retries, timeouts,
cancellation propagation, strict Pydantic response validation, error
classification, accounting, safe logging, and provider health checks.

Role configuration comes from `.env.example` variables such as
`MODEL_REQUIREMENTS`, `MODEL_GEOMETRY`, and their `_FALLBACKS` counterparts.
The desktop Model Orchestration dialog displays provider, model, fallback,
timeout, enabled state, and health without exposing credentials. The selected
desktop model can be assigned to every role for the common single-model case.

The current natural-language compatibility agent remains available. New
engineering planners should call the role router in workflow order and emit
DesignIR rather than raw CST code. Independent lookup/calculation work may run
concurrently; geometry, booleans, ports, validation, and compilation remain
sequential.

## Adding a provider

Implement `generate_structured()` and `health()` from the provider protocol,
validate into the requested Pydantic schema, never log authorization headers,
register the provider by a non-secret ID, and add retry/fallback/accounting
tests.
