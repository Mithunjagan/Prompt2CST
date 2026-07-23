# Architecture

```mermaid
flowchart LR
    UI["Qt Quick RF workspace"] --> Agent["OpenRouter tool agent"]
    Agent --> MCP["Local typed MCP server"]
    MCP --> Preview["Validated previews"]
    MCP --> CST["CST 2026 COM bridge"]
    Preview --> Approval["User approval sheet"]
    Approval --> CST
```

The model never receives a general code-execution tool. Preview and build are
separate operations. The desktop controller requests approval only for a typed
CST-writing tool, and the build continues only when the user accepts the exact
arguments and calculated preview.
