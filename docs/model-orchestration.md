# Model orchestration

Prompt2CST uses a sequential specialist swarm. Eight model roles are
configurable independently:

- requirements
- calculations
- parameters
- geometry
- simulation
- critic
- code review
- results analysis

The desktop runtime uses the first six planning roles. Code review is a
development role, and results analysis is reserved for extracted CST results.
Preview and Build are deterministic services, not model roles.

| Phase | Owner | Output |
|---|---|---|
| requirements | `requirements_model` | `RequirementsArtifact` |
| calculations | deterministic calculator + `calculations_model` | numeric calculation records + `RFReasoningArtifact` |
| parameters | `parameters_model` | `ParameterArtifact` |
| modeling | `geometry_model` | `GeometryArtifact` containing strict DesignIR |
| simulation | `simulation_model` | `SimulationArtifact` merged into DesignIR |
| validation | deterministic validator + `critic_model` | validation report + `CriticArtifact` |
| preview | swarm coordinator + PlanService | compiled immutable plan and SHA-256 hash |
| build | deterministic executor | exact approved CST operation sequence |

`ModelProvider` defines structured generation. The repository includes an
OpenAI-compatible provider for OpenRouter, a mock provider, per-role routing,
fallbacks, bounded retries, role timeouts, cancellation propagation, strict
Pydantic response validation, error classification, accounting, safe logging,
and provider health checks.

Role configuration comes from `.env.example` variables such as
`MODEL_REQUIREMENTS`, `MODEL_CALCULATIONS`, `MODEL_PARAMETERS`,
`MODEL_GEOMETRY`, and their `_FALLBACKS` counterparts. The older
`MODEL_RF_REASONING` variables remain accepted as a compatibility fallback for
the calculations and parameters roles.

The desktop Model Orchestration dialog displays provider, model, fallbacks,
timeout, enabled state, and health without exposing credentials. Assign one
model to all roles for a simple setup, or assign different models to individual
roles. The coordinator records the actual provider/model, retries, token
accounting, tool-call count, and fallbacks in the swarm session and immutable
preview.

## Handoff and revision rules

- Every specialist receives only the artifacts it needs and returns one strict
  schema.
- Geometry output cannot own simulation configuration; the coordinator removes
  those fields before handing DesignIR to the simulation specialist.
- Deterministic numeric results are passed to models as read-only evidence.
- Deterministic blocking validation cannot be changed by the critic verdict.
- Reusing the same prompt for a later phase resumes from the last typed
  checkpoint. A changed prompt increments the conversation revision,
  invalidates downstream artifacts, and revokes any prior awaiting-approval
  plan.
- Build performs zero model calls and can only consume the current saved
  preview.

## Adding a provider

Implement `generate_structured()` and `health()` from the provider protocol,
validate into the requested Pydantic schema, never log authorization headers,
register the provider by a non-secret ID, and add retry, fallback, provenance,
and malformed-output tests.
