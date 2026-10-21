# Iteration policy — tracks vs concerns

**Status:** stable (v1)  
**Applies to:** multi-track DH projects using `docs/state.json` / `scripts/svz.py`  
**Portable:** yes  
**Pilot origin:** `republic_ner_matching` (`docs/ITERATION_POLICY.md`)  
**Companion:** [iteration-decision-framework](iteration-decision-framework.md), [cost-sensitive-agent-workflow](cost-sensitive-agent-workflow.md)

## Rule

At **session start**, run `uv run python scripts/svz.py review` and read **Active tracks needing a decision** before choosing what to work on.

Within a chosen track, if `plans/iteration.toml` exists, call `workflow-orchestrator advise` (or MCP `get_iteration_advice`) before retrying the **same concern**.

```text
svz review              → which TRACK next?
iteration advise        → within that track, another polish pass on CONCERN X?
svz metric / decision   → evidence + durable stop/continue
```

## Two layers

| Layer | Artefact | Question |
|-------|----------|----------|
| **Tracks** | `docs/state.json` tasks + metrics | Which research line gets this session? |
| **Concerns** | `plans/iteration.toml` + `iteration_log.jsonl` | Is another pass on this knot allowed? |

Do not collapse them: track choice needs **metric trends**; concern polish needs **stage gates / budgets / interlocks**.

## Install in any existing repo

Canonical path — run from a local clone of [dighum_template](https://github.com/HoekR/dighum_template):

```bash
# 1. Tracks: SvZ CLI + wisdom topics (iteration-policy, decision framework, …)
./scripts/sync_project.sh /path/to/repo --state --wisdom

# 2. Concerns (optional): editable gates beside PLAN
mkdir -p /path/to/repo/plans
cp packages/workflow_mcp/examples/iteration.toml /path/to/repo/plans/iteration.toml
# Rename stages/concerns/facts for that project.

# 3. Agent wiring (optional): MCP + AGENTS snippet
./scripts/sync_project.sh /path/to/repo --mcp --addon workflow-mcp
```

Then in the project: keep `docs/state.json` tasks current; after targeted passes run `uv run python scripts/svz.py metric …`; at session start run `svz.py review`. Before retrying the same concern: `workflow-orchestrator advise` or MCP `get_iteration_advice`.

New repos: `bootstrap.sh … --with-wisdom` already ships `scripts/svz.py`; still copy `plans/iteration.toml` and apply `workflow-mcp` if you want concern gates. Sync flags: [SYNC-PROJECT.md](../../docs/SYNC-PROJECT.md).

## Definitions (tracks)

- **Improving**: latest recorded delta on a metric exceeds the relative threshold (default 3%, `--threshold` on `review`), in the direction that matters (state it when recording — F1 up good; error-rate down → record inverted value if needed).
- **Stagnant / cutoff candidate**: most recent delta within threshold of zero. One stagnant reading is a **flag**, not a verdict — check whether that session actually targeted the metric.
- **Structural ceiling**: a documented, verified reason further work cannot move the metric (missing data, zero-overlap GT, coverage bound). Backed by a diagnostic, not “we tried a bit.”

## Choosing the next track

1. Prefer a track flagged **improving**, or one with a concrete scoped next action, over one that needs new tooling or unverified data from scratch.
2. Among ready tracks, prefer more remaining headroom below a plausible ceiling.
3. A **stagnant** track is not automatically dropped. Only treat **repeated (2+) stagnant readings after sessions that targeted the metric** as a real close signal.
4. On **structural ceiling** or missing prerequisite data: `svz.py decision …` and set task status `done` or `blocked` — do not leave `inprogress` forever.
5. `svz.py review` classifies trend direction only; the continue/switch/stop call stays with the human (or agent-as-advisor).

## Mechanism (`svz.py`)

```bash
uv run python scripts/svz.py review
uv run python scripts/svz.py metric <task-id> <metric-name> <value> --label "…"
uv run python scripts/svz.py decision "Title" --context "…" --decision "…" --reason "…"
```

- Metrics append to `history` (same calendar day overwrites the last point).
- A track with **no** recorded metric cannot be judged — record one; do not skip the check.
- Scope is the task `id`, or `<id>-<subid>` for a diagnostic under that track.

## Anti-patterns

| Wrong | Right |
|-------|-------|
| Multiple sessions with no `svz.py metric` | Record after each targeted pass |
| One stagnant reading → hard stop | Check targeting; need 2+ after targeted work |
| Assume design-doc data still exists | Verify files for this project's scope |
| Ceiling hit but task stays `inprogress` | Decision entry + `done` / `blocked` |
| Only use orchestrator, ignore tracks | `review` first when several tracks compete |
| Only use `review`, ignore stage gates | `advise` before the third identical polish pass |

## See also

- Template: `template/scripts/svz.py`
- Orchestrator: [iteration-decision-framework](iteration-decision-framework.md)
- Cost-sensitive sessions: [cost-sensitive-agent-workflow](cost-sensitive-agent-workflow.md)
