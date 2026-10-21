#!/usr/bin/env python3
"""Manage the lightweight project state dashboard (SvZ).

The machine source of truth is docs/state.json. docs/STATE.md is rendered from
that file so AI agents and humans can read a compact, visual dashboard.

`review` supports the continue/switch/stop discipline in
docs/wisdom/iteration-policy.md (or the project's copy): it classifies each
track's latest recorded metric delta (improving / stagnant / regressing) so a
session can start by asking "which track has the clearest next gain" instead of
resuming whatever was last open.

Compose with workflow-mcp iteration orchestrator (plans/iteration.toml) for
within-track polish gates — see wisdom iteration-decision-framework.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


STATE_JSON = Path("docs/state.json")
STATE_MD = Path("docs/STATE.md")
DECISIONS_MD = Path("docs/DECISIONS.md")
MANUAL_MARKER = "<!-- Manual notes below this line are preserved by scripts/svz.py render. -->"
VALID_STATUSES = {"todo", "inprogress", "done", "blocked"}
DEFAULT_TREND_THRESHOLD = 0.03


def now_stamp() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def today_date() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def load_state() -> dict[str, Any]:
    if not STATE_JSON.exists():
        raise SystemExit(f"Missing {STATE_JSON}. Run from the project root or create state.json first.")
    return json.loads(STATE_JSON.read_text(encoding="utf-8"))


def save_state(state: dict[str, Any]) -> None:
    state["last_updated"] = now_stamp()
    STATE_JSON.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def task_symbol(status: str) -> str:
    return {"done": "x", "inprogress": "/", "blocked": "!"}.get(status, " ")


def mermaid_class(status: str) -> str:
    return status if status in VALID_STATUSES else "todo"


def mermaid_id(task_id: str) -> str:
    clean = re.sub(r"[^A-Za-z0-9_]", "_", task_id)
    return clean if clean and clean[0].isalpha() else f"T_{clean}"


def find_task(state: dict[str, Any], task_id: str) -> dict[str, Any] | None:
    for task in state.get("tasks", []):
        if task.get("id") == task_id:
            return task
    return None


def parse_number(value: Any) -> float | None:
    """Best-effort numeric read of a metric value: '0.576', '70.7%', '9/21'."""
    text = str(value).strip()
    if not text:
        return None
    fraction = re.fullmatch(r"(-?\d+(?:\.\d+)?)\s*/\s*(-?\d+(?:\.\d+)?)", text)
    if fraction:
        numerator, denominator = (float(part) for part in fraction.groups())
        return numerator / denominator if denominator else None
    is_percent = text.endswith("%")
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    if not match:
        return None
    number = float(match.group())
    return number / 100 if is_percent else number


def classify_trend(history: list[dict[str, Any]], threshold: float) -> tuple[str, float | None]:
    """Compare the two most recent numeric history points.

    Returns (verdict, delta) where verdict is one of:
    "improving", "stagnant", "regressing", "insufficient-history".
    Direction is read literally (higher = improving) — invert the metric's own
    value at recording time (e.g. record 1 - other_bucket_pct) if lower is better.
    """
    numeric_points = [parse_number(point.get("value")) for point in history]
    numeric_points = [value for value in numeric_points if value is not None]
    if len(numeric_points) < 2:
        return "insufficient-history", None
    previous, latest = numeric_points[-2], numeric_points[-1]
    delta = latest - previous
    relative = delta / abs(previous) if previous else (None if delta == 0 else delta)
    if relative is None:
        verdict = "stagnant"
    elif relative > threshold:
        verdict = "improving"
    elif relative < -threshold:
        verdict = "regressing"
    else:
        verdict = "stagnant"
    return verdict, delta


def preserved_notes() -> str:
    if not STATE_MD.exists():
        return "## Notes\n\n"
    content = STATE_MD.read_text(encoding="utf-8")
    if MANUAL_MARKER not in content:
        return "## Notes\n\n"
    return content.split(MANUAL_MARKER, 1)[1].lstrip()


def render_markdown(state: dict[str, Any]) -> str:
    tasks = state.get("tasks", [])
    metrics = state.get("metrics", [])
    blockers = state.get("blockers", [])
    dependencies = state.get("dependencies", [])
    next_actions = state.get("next_actions", [])
    last_updated = state.get("last_updated") or "not set"

    lines: list[str] = [
        "# Current Project State (SvZ)",
        "",
        f"Last updated: {last_updated}",
        "",
        "```mermaid",
        "flowchart TD",
        "    classDef done fill:#2e7d32,stroke:#1b5e20,color:#fff,stroke-width:2px;",
        "    classDef inprogress fill:#f57c00,stroke:#e65100,color:#fff,stroke-width:2px;",
        "    classDef todo fill:#424242,stroke:#212121,color:#ddd,stroke-width:1px,stroke-dasharray: 5 5;",
        "    classDef blocked fill:#c62828,stroke:#b71c1c,color:#fff,stroke-width:2px;",
        "",
    ]
    for task in tasks:
        node_id = mermaid_id(str(task.get("id", "task")))
        label = f"{task.get('id', '')}: {task.get('title', '')}".replace('"', "'")
        lines.append(f"    {node_id}[\"{label}\"] :::{mermaid_class(str(task.get('status', 'todo')))}")
    if dependencies:
        for dependency in dependencies:
            source = mermaid_id(str(dependency.get("from", "")))
            target = mermaid_id(str(dependency.get("to", "")))
            if source and target:
                lines.append(f"    {source} --> {target}")
    else:
        for first, second in zip(tasks, tasks[1:]):
            lines.append(f"    {mermaid_id(str(first.get('id', '')))} --> {mermaid_id(str(second.get('id', '')))}")
    lines.extend(["```", "", "## Overall Progress", ""])

    if tasks:
        for task in tasks:
            status = str(task.get("status", "todo"))
            task_line = f"- [{task_symbol(status)}] {task.get('id')}: {task.get('title')}"
            if task.get("notes"):
                task_line += f" — {task['notes']}"
            lines.append(task_line)
    else:
        lines.append("No tasks recorded yet.")

    lines.extend(["", "## Active Focus", "", str(state.get("active_focus") or "No active focus recorded."), ""])
    lines.extend(["## Key Intermediate Results & Metrics", ""])
    if metrics:
        for metric_entry in metrics:
            value = metric_entry.get("value", "")
            label = metric_entry.get("label") or metric_entry.get("name") or "metric"
            scope = metric_entry.get("scope")
            prefix = f"{scope} — " if scope else ""
            verdict, delta = classify_trend(metric_entry.get("history", []), DEFAULT_TREND_THRESHOLD)
            trend = f" ({verdict}, Δ{delta:+.3f})" if delta is not None else ""
            lines.append(f"- **{prefix}{label}:** {value}{trend}")
    else:
        lines.append("No metrics recorded yet.")

    lines.extend(["", "## Blockers / Open Questions", ""])
    if blockers:
        lines.extend(f"- [ ] {item}" for item in blockers)
    else:
        lines.append("No blockers recorded.")

    lines.extend(["", "## Next Actions", ""])
    if next_actions:
        lines.extend(f"- {item}" for item in next_actions)
    else:
        lines.append("No next actions recorded.")

    lines.extend(["", MANUAL_MARKER, preserved_notes().rstrip(), ""])
    return "\n".join(lines)


def render(_: argparse.Namespace) -> None:
    state = load_state()
    STATE_MD.write_text(render_markdown(state), encoding="utf-8")
    print(f"Rendered {STATE_MD} from {STATE_JSON}")


def status(_: argparse.Namespace) -> None:
    state = load_state()
    print(f"Project: {state.get('project', 'unknown')}")
    print(f"Last updated: {state.get('last_updated') or 'not set'}")
    print(f"Active focus: {state.get('active_focus') or 'none'}")
    print("\nTasks:")
    for task in state.get("tasks", []):
        print(f"  [{task_symbol(str(task.get('status', 'todo')))}] {task.get('id')}: {task.get('title')}")
    if state.get("metrics"):
        print("\nMetrics:")
        for metric_entry in state["metrics"]:
            scope = f"{metric_entry.get('scope')}: " if metric_entry.get("scope") else ""
            print(f"  - {scope}{metric_entry.get('label') or metric_entry.get('name')}: {metric_entry.get('value')}")


def update(args: argparse.Namespace) -> None:
    if args.status not in VALID_STATUSES:
        raise SystemExit(f"Status must be one of: {', '.join(sorted(VALID_STATUSES))}")
    state = load_state()
    task = find_task(state, args.task_id)
    if task is None:
        task = {"id": args.task_id, "title": args.title or args.task_id, "status": args.status, "notes": ""}
        state.setdefault("tasks", []).append(task)
    else:
        task["status"] = args.status
        if args.title:
            task["title"] = args.title
    if args.notes is not None:
        task["notes"] = args.notes
    save_state(state)
    STATE_MD.write_text(render_markdown(state), encoding="utf-8")
    print(f"Set {args.task_id} to {args.status}")


def focus(args: argparse.Namespace) -> None:
    state = load_state()
    state["active_focus"] = args.text
    save_state(state)
    STATE_MD.write_text(render_markdown(state), encoding="utf-8")
    print("Updated active focus")


def metric(args: argparse.Namespace) -> None:
    """Record a metric value; append to history (same day overwrites last point)."""
    state = load_state()
    today = today_date()
    metrics = state.setdefault("metrics", [])
    for existing in metrics:
        if existing.get("scope") == args.scope and existing.get("name") == args.name:
            history = existing.setdefault("history", [])
            if history and history[-1].get("date") == today:
                history[-1]["value"] = args.value
            else:
                history.append({"date": today, "value": args.value})
            existing["value"] = args.value
            if args.label:
                existing["label"] = args.label
            break
    else:
        metrics.append(
            {
                "scope": args.scope,
                "name": args.name,
                "label": args.label or args.name,
                "value": args.value,
                "history": [{"date": today, "value": args.value}],
            }
        )
    save_state(state)
    STATE_MD.write_text(render_markdown(state), encoding="utf-8")
    print(f"Recorded metric {args.name}={args.value}")


def decision(args: argparse.Namespace) -> None:
    DECISIONS_MD.parent.mkdir(parents=True, exist_ok=True)
    if not DECISIONS_MD.exists():
        DECISIONS_MD.write_text("# Decision Log\n\n", encoding="utf-8")
    entry = (
        f"\n## {datetime.now().strftime('%Y-%m-%d')}: {args.title}\n\n"
        f"- **Context:** {args.context}\n"
        f"- **Decision:** {args.decision}\n"
        f"- **Reason:** {args.reason}\n"
    )
    with DECISIONS_MD.open("a", encoding="utf-8") as handle:
        handle.write(entry)
    print(f"Appended decision to {DECISIONS_MD}")


def query(args: argparse.Namespace) -> None:
    state = load_state()
    haystack = json.dumps(state, ensure_ascii=False, indent=2).lower()
    if args.term.lower() not in haystack:
        print(f"No matches for {args.term!r}")
        return
    print(json.dumps(state, ensure_ascii=False, indent=2))


def review(args: argparse.Namespace) -> None:
    state = load_state()
    threshold = args.threshold
    by_scope: dict[str, list[dict[str, Any]]] = {}
    for metric_entry in state.get("metrics", []):
        by_scope.setdefault(str(metric_entry.get("scope")), []).append(metric_entry)

    active, pending, closed = [], [], []
    for task in state.get("tasks", []):
        bucket = {"inprogress": active, "todo": pending}.get(str(task.get("status", "todo")), closed)
        bucket.append(task)

    print("== Active tracks needing a decision ==")
    if not active:
        print("  (none marked inprogress)")
    for task in active:
        print(f"- {task.get('id')}: {task.get('title')}")
        task_metrics = by_scope.get(str(task.get("id")), [])
        if not task_metrics:
            print("    no metric recorded — run `svz.py metric ...` before judging this track")
            continue
        for metric_entry in task_metrics:
            verdict, delta = classify_trend(metric_entry.get("history", []), threshold)
            delta_str = f"{delta:+.3f}" if delta is not None else "n/a"
            flag = "  <- cutoff candidate" if verdict == "stagnant" else ""
            print(f"    {metric_entry.get('label')}: {metric_entry.get('value')} (Δ {delta_str}, {verdict}){flag}")

    print("\n== Not started ==")
    if not pending:
        print("  (none)")
    for task in pending:
        note = f" — {task['notes']}" if task.get("notes") else ""
        print(f"- {task.get('id')}: {task.get('title')}{note}")

    print("\n== Closed (done / blocked) ==")
    if not closed:
        print("  (none)")
    for task in closed:
        note = f" — {task['notes']}" if task.get("notes") else ""
        print(f"- [{task.get('status')}] {task.get('id')}: {task.get('title')}{note}")

    print(
        "\nSee docs/wisdom/iteration-policy.md (or dighum_template wisdom) before "
        "switching tracks or recording a cutoff (`svz.py decision ...`). "
        "Within a track, use workflow-orchestrator advise if plans/iteration.toml exists."
    )


def doctor(_: argparse.Namespace) -> None:
    state = load_state()
    problems: list[str] = []
    task_ids = [task.get("id") for task in state.get("tasks", [])]
    if len(task_ids) != len(set(task_ids)):
        problems.append("Duplicate task ids in docs/state.json")
    for task in state.get("tasks", []):
        if task.get("status") not in VALID_STATUSES:
            problems.append(f"Invalid status for {task.get('id')}: {task.get('status')}")
    task_id_set = {str(task_id) for task_id in task_ids}
    for metric_entry in state.get("metrics", []):
        scope = str(metric_entry.get("scope"))
        if scope not in task_id_set and not any(scope.startswith(f"{task_id}-") for task_id in task_id_set):
            problems.append(
                f"Metric {metric_entry.get('name')!r} has scope {metric_entry.get('scope')!r} "
                "that does not match any task id (or <task_id>-<subid> pattern)"
            )
    if problems:
        for problem in problems:
            print(f"ERROR: {problem}", file=sys.stderr)
        raise SystemExit(1)
    print("SvZ state looks valid")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage docs/state.json and render docs/STATE.md.")
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("status", help="Print a compact state summary").set_defaults(func=status)
    subparsers.add_parser("render", help="Render docs/STATE.md from docs/state.json").set_defaults(func=render)
    subparsers.add_parser("doctor", help="Validate docs/state.json").set_defaults(func=doctor)

    update_parser = subparsers.add_parser("update", help="Set or create a task status")
    update_parser.add_argument("task_id")
    update_parser.add_argument("status", choices=sorted(VALID_STATUSES))
    update_parser.add_argument("--title")
    update_parser.add_argument("--notes")
    update_parser.set_defaults(func=update)

    focus_parser = subparsers.add_parser("focus", help="Set the active focus text")
    focus_parser.add_argument("text")
    focus_parser.set_defaults(func=focus)

    metric_parser = subparsers.add_parser(
        "metric",
        help="Record or update a metric (appends to its history)",
    )
    metric_parser.add_argument("scope", help="Task id this metric belongs to")
    metric_parser.add_argument("name")
    metric_parser.add_argument("value")
    metric_parser.add_argument("--label")
    metric_parser.set_defaults(func=metric)

    decision_parser = subparsers.add_parser("decision", help="Append a decision log entry")
    decision_parser.add_argument("title")
    decision_parser.add_argument("--context", required=True)
    decision_parser.add_argument("--decision", required=True)
    decision_parser.add_argument("--reason", required=True)
    decision_parser.set_defaults(func=decision)

    query_parser = subparsers.add_parser("query", help="Print state JSON if a term appears in it")
    query_parser.add_argument("term")
    query_parser.set_defaults(func=query)

    review_parser = subparsers.add_parser(
        "review",
        help="Classify each track's latest metric trend (continue/switch/stop aid)",
    )
    review_parser.add_argument(
        "--threshold",
        type=float,
        default=DEFAULT_TREND_THRESHOLD,
        help=(
            f"Relative delta magnitude below which a metric counts as stagnant "
            f"(default {DEFAULT_TREND_THRESHOLD})"
        ),
    )
    review_parser.set_defaults(func=review)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not hasattr(args, "func"):
        args = parser.parse_args(["status"])
    args.func(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
