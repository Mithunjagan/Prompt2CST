# Security design

Model-generated content is untrusted. Strict schemas reject unknown fields and
the safe expression parser rejects code execution, imports, attributes, file
paths, network access, and arbitrary functions.

Desktop planning models receive only role-specific messages and response
schemas; they receive no CST-writing tool. Geometry-owned and
simulation-owned DesignIR sections are separated by coordinator enforcement.
RF arithmetic and blocking validation remain deterministic even when a model
returns a conflicting explanation.

Only the deterministic compiler creates CST commands. Preview performs schema,
dependency, capability, geometry, material, port, simulation, mesh, and sweep
validation; compiles the operation sequence; writes an immutable local plan;
and returns a SHA-256 approval hash. A new conversation revision explicitly
moves the prior workflow out of `AWAITING_APPROVAL`, so retaining an old plan
ID and hash cannot execute a superseded preview.

Execution requires an existing plan ID, the matching hash, and explicit human
approval. The controller persists an approval record after the native approval
sheet returns true; a caller-supplied `approved=true` boolean is insufficient.
Only `execute_approved_plan` can reach `CSTBridge`; legacy `build_*` tools now
produce immutable DesignIR previews. Execution uses a new CST project, persists
completed operation IDs, stops on the exact failed operation, and never claims
solver success.

Provider secrets stay in backend process memory or approved environment
configuration. QML settings expose model IDs, not keys. Secret-shaped values
are redacted from orchestration logs. State paths accept opaque alphanumeric
IDs and CST project names remain confined to the configured output directory.

Security tests cover code-injection expressions, path injection, schema extra
fields, approval bypass, plan mutation, secret redaction, missing materials,
invalid ports, unsupported capabilities, exact specialist ordering, preview
invalidation, approval denial, and zero-model-call exact-plan execution.
