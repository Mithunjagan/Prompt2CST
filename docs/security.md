# Security design

Model-generated content is untrusted. Strict schemas reject unknown fields and
the safe expression parser rejects code execution, imports, attributes, file
paths, network access, and arbitrary functions.

Only the deterministic compiler creates CST commands. Preview performs schema,
dependency, capability, geometry, material, port, simulation, mesh, and sweep
validation; compiles the operation sequence; writes an immutable local plan;
and returns a SHA-256 approval hash. Any stored or submitted change invalidates
approval.

Execution requires an existing plan ID, the matching hash, and explicit human
approval. It uses a new CST project, persists completed operation IDs, stops on
the exact failed operation, and never claims solver success.

Provider secrets stay in backend process memory or approved environment
configuration. QML settings expose model IDs, not keys. Secret-shaped values
are redacted from orchestration logs. State paths accept opaque alphanumeric
IDs and CST project names remain confined to the configured output directory.

Security tests cover code-injection expressions, path injection, schema extra
fields, approval bypass, plan mutation, secret redaction, missing materials,
invalid ports, and unsupported capabilities.
