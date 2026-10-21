# Iteration decision framework

**Status:** stable (v1)  
**Applies to:** multi-step DH pipelines with iterative loops (eval, specs, gold/labels, prompts, figures)  
**Portable:** yes  
**Companion:** [iteration-policy](iteration-policy.md), [cost-sensitive-agent-workflow](cost-sensitive-agent-workflow.md), [workflow-mcp](workflow-mcp.md)

## Rule

Before retrying the **same concern** (metric, spec, tooling knot):

1. Name the concern.
2. Ask the orchestrator (`get_iteration_advice` / CLI `advise`) whether to continue.
3. If the verdict is not `continue`, **stop polishing** — escalate upstream, defer, change success criteria, or ask a human.

Do not burn attempts on a knot that cannot unlock at the current stage.

## Problem this solves

1. **Premature loops** — polishing a metric or prompt before inputs, labels, or success criteria exist.
2. **Interlocks** — A↔B↔C co-constrain; linear “finish A then B” fails, but unbounded coupled iteration becomes (1).

Cost-sensitive workflow already enforces **one PLAN step per chat**. This framework adds **stage gates, attempt budgets, and interlock-aware advice** beside PLAN — not a second plan.

## Concepts (all editable in `plans/iteration.toml`)

| Concept | Meaning |
|---------|---------|
| **Stages** | Ordered capability layers (e.g. `inputs_ready` → `baseline_eval` → `method_calibrate`). Each has `requires_facts` / `requires_stages` and `done_when`. |
| **Concerns** | Named work loops inside a stage (`metric_chase`, `spec_tweaks`). Each has `max_attempts` and `escalate_to`. |
| **Interlocks** | Pairs: if A moves, revisit B (`blocking = true` → defer until partner open). |
| **Verdicts** | `continue` \| `escalate_upstream` \| `defer` \| `change_success_criteria` \| `ask_human` |
| **Facts** | Project booleans in `[facts]` (gates without code changes). |

Names are **project-local** — annotation, Bayesian, corpus prep, and publication projects should rename stages/concerns to match their domain.

## Kill / escalate heuristics

| Condition | Verdict |
|-----------|---------|
| Prerequisite stage/fact missing | `escalate_upstream` |
| Attempts ≥ `max_attempts` | concern’s `escalate_to` (default `change_success_criteria`) |
| Blocking interlock partner still open | `defer` (or paired pass — touch both) |
| Stage marked done and concern not `reopen` | `ask_human` |
| Otherwise | `continue` |

## Adjustable design

Project file (optional):

```text
plans/iteration.toml      # stages, concerns, interlocks, facts
plans/iteration_log.jsonl # append-only attempts (orchestrator writes)
```

Generic example: `dighum_template/packages/workflow_mcp/examples/iteration.toml`.

Schema sketch:

```toml
[meta]
version = 1

[facts]
inputs_registered = true
eval_harness_ready = true

[[stages]]
id = "method_calibrate"
requires_facts = ["eval_harness_ready"]
requires_stages = ["baseline_eval"]
done_when = "Method stable enough for a second eval pass"

[[concerns]]
id = "metric_chase"
stage = "method_calibrate"
max_attempts = 3
escalate_to = "change_success_criteria"

[[interlocks]]
a = "label_style"
b = "eval_strictness"
blocking = true
```

## Orchestrator (advisor only)

Lives in **workflow_mcp** — CLI + MCP tools. Does **not** auto-run steps, auto-tick `PLAN.md`, or write `svz`/`state.json`.

```bash
uv run --directory ~/develop/dighum_template/packages/workflow_mcp \
  workflow-orchestrator advise --project-root . --concern metric_chase

uv run --directory ~/develop/dighum_template/packages/workflow_mcp \
  workflow-orchestrator record --project-root . --concern metric_chase \
  --outcome no_gain --note "same metric, no unlock"
```

MCP: `get_iteration_advice`, `record_iteration_attempt`, `get_iteration_config`.

On `ask_human` / `escalate_upstream`, the CLI may suggest a `svz decision …` line — human runs it.

## Compose with existing tools

| Tool | Role |
|------|------|
| `PLAN.md` + `plans/steps/` | Human progress authority; one step per chat |
| **`svz.py review`** | Which **track** next (metric trends) — see [iteration-policy](iteration-policy.md) |
| workflow-mcp / orchestrator | Within a track: stage gates, budgets, interlocks on a **concern** |
| plan-step-executor | One bounded PLAN step; call advice before retrying same concern |
| `svz.py metric` / `decision` | Evidence history + durable stop/continue |

Session shape:

1. `uv run python scripts/svz.py review`
2. Pick a track (or PLAN step).
3. If polishing the same concern: `workflow-orchestrator advise --concern …`
4. After the pass: `record` attempt and/or `svz.py metric <track> …`

## Anti-patterns

| Wrong | Right |
|-------|-------|
| Third pass on the same metric “just to see” | `advise` → if over budget, change criteria or escalate |
| Tuning eval before inputs/labels exist | Stage gate → `escalate_upstream` |
| Ignoring interlocks (label style vs eval bar) | Declare `[[interlocks]]`; defer or paired pass |
| Hard-coding one project’s stage names in the template | Copy example; rename for your pipeline |
| Orchestrator ticks PLAN | Human ticks PLAN; orchestrator only logs attempts |

## Why

Long agent/human loops burn budget on unsolvable knots. An explicit, **project-editable** gate file makes “should I keep iterating?” a single verdict instead of vibes.
