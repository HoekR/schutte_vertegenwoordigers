# workflow MCP server

**Status:** stable (v1)  
**Applies to:** multi-step DH projects with `PLAN.md` + `plans/steps/`  
**Portable:** yes (server in `dighum_template/packages/workflow_mcp`)

## Rule

Use the **workflow MCP** at session start and when the user says **start/guide step N** — read one step guide via MCP, not the whole repo plan.

## Tools

| Tool | Purpose |
|------|---------|
| `get_plan_status()` | Parsed `PLAN.md` checklist |
| `get_current_step()` | First incomplete step |
| `list_steps()` | Index of `plans/steps/STEP*.md` (fallback: `docs/steps/`) |
| `get_step_guide(step_id)` | Single step markdown |
| `get_workflow_rules()` | `docs/wisdom/cost-sensitive-agent-workflow.md` if present |
| `get_iteration_advice(concern_id)` | Stage gates / budgets / interlocks (`plans/iteration.toml`) |
| `record_iteration_attempt(...)` | Append `plans/iteration_log.jsonl` (not PLAN) |
| `get_iteration_config()` | Effective iteration.toml |

## Optional dependency: dighum_template

Derivatives reference — not vendor — the server in [dighum_template](https://github.com/HoekR/dighum_template) `packages/workflow_mcp/`. Clone once as a sibling; add-on overlay copies only `.cursor/mcp.json` stub and docs. Optional: skip if you do not use Cursor MCP.

## Setup

1. `cd ~/develop/dighum_template/packages/workflow_mcp && uv sync`
2. Apply add-on: `apply_addon.sh <project> workflow-mcp`
3. Merge `.cursor/mcp.json.example` → `.cursor/mcp.json` (combine with `data-io` if needed)
4. `${workspaceFolder}` must point at the DH project root
5. Optional: copy `packages/workflow_mcp/examples/iteration.toml` → `plans/iteration.toml`

## Why

Agents load entire plans, skip step boundaries, and run multi-step shell loops. MCP exposes the same **one-step-at-a-time** contract as `AGENTS.md` at tool-call time. Iteration tools stop **premature polish loops** when stage gates or attempt budgets say stop.

## Not in v1

- Running terminal commands
- Cross-project step templates (steps stay in each repo's `plans/steps/`, created on demand)
- Auto-ticking `PLAN.md` from the orchestrator
- Writing `svz` / `state.json` (CLI may print a suggested `svz decision` line only)

## Related

- [cost-sensitive-agent-workflow](cost-sensitive-agent-workflow.md)
- [iteration-decision-framework](iteration-decision-framework.md)
- [iteration-policy](iteration-policy.md) — `svz review` (tracks) vs orchestrator concerns
- [data-io-mcp](data-io-mcp.md)
- Package: `packages/workflow_mcp/README.md`
