# MCP Adapter Scope

`stratum/mcp_adapter` is an additive adapter layer for future MCP-style
transport. It depends on `stratum.capabilities` and does not touch production
pipeline orchestration.

The package entrypoint `stratum.mcp_adapter` is the stable import surface for
tool descriptors and tool-call delegation.

## Responsibilities

- Expose MCP-style tool descriptors for capability-layer functions.
- Delegate tool calls to `stratum.capabilities.call`.
- Keep tool discovery and invocation transport-neutral until a real MCP server
  is introduced.

## Non-Responsibilities

- Does not run a network server or stdio protocol loop.
- Does not call stage CLIs or orchestrator internals directly.
- Does not replace the current production pipeline.
- Does not define new business logic beyond adapter metadata.

## Stable Surface

| Surface | Canonical Owner | Purpose |
|:---|:---|:---|
| `list_tools` | `stratum.mcp_adapter.tools` | Return MCP-style tool descriptors. |
| `get_tool` | `stratum.mcp_adapter.tools` | Return one MCP-style tool descriptor. |
| `call_tool` | `stratum.mcp_adapter.tools` | Delegate one MCP-style tool call to the capability layer. |

## Design Rules

- Tool descriptors must point to capability-layer surfaces, not to pipeline
  stages or orchestrator helpers.
- Adapter metadata must stay additive and stable.
- Any future MCP server should wrap this package before touching deeper
  internals.
