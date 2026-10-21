"""Flask UI for Schutte lemma structure review (zones + soft whiteline breaks).

Mirrors republic_ner ``lumped_paragraph_labeller`` / trifecta ``gold_labeller``:
prev/next, verdict + note, JSON persistence on every save.

Default queue is a stratified ~50-lemma sample (warn/fail + chapter mix).
Pass ``?mode=all`` to browse the full corpus.

Usage::

    cd lemma_extractor
    uv sync --extra review
    uv run schutte-structure-ui
    # http://127.0.0.1:5080
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from flask import Flask, abort, jsonify, redirect, render_template, request, url_for

from structure_labeller.store import (
    DEFAULT_SAMPLE_SIZE,
    SEPARATOR_ROLES,
    VERDICTS,
    annotations_path,
    build_review_sample,
    header_summary,
    load_annotations,
    load_candidates,
    load_structure_preview,
    merge_row,
    next_unlabelled_id,
    record_index,
    save_annotations,
    stats,
    update_annotation,
)

TEMPLATE_DIR = Path(__file__).parent / "templates"
STATIC_DIR = Path(__file__).parent / "static"
# Avoid 5060 — Firefox blocks it as SIP (restricted port).
DEFAULT_PORT = 5080
MODES = ("sample", "all")


@lru_cache(maxsize=1)
def _cached_candidates() -> tuple[dict, ...]:
    return tuple(load_candidates())


def _parse_mode(raw: str | None) -> str:
    mode = (raw or "sample").strip().lower()
    return mode if mode in MODES else "sample"


def create_app() -> Flask:
    app = Flask(
        __name__,
        template_folder=str(TEMPLATE_DIR),
        static_folder=str(STATIC_DIR),
    )

    def _all_candidates() -> list[dict]:
        return list(_cached_candidates())

    def _annotations():
        return load_annotations()

    def _queue(mode: str) -> list[dict]:
        all_cands = _all_candidates()
        if mode == "all":
            return all_cands
        return build_review_sample(all_cands, _annotations(), size=DEFAULT_SAMPLE_SIZE)

    def _label_url(example_id: str, mode: str) -> str:
        return url_for("label_record", example_id=example_id, mode=mode)

    @app.get("/")
    def index():
        mode = _parse_mode(request.args.get("mode"))
        queue = _queue(mode)
        if not queue:
            return "<p>No lemma candidates (check Excel / TOC paths).</p>", 404
        ann = _annotations()
        example_id = next_unlabelled_id(queue, ann)
        if not example_id:
            for c in queue:
                if c.get("header_status") in ("fail", "warn"):
                    example_id = str(c["example_id"])
                    break
            example_id = example_id or str(queue[0]["example_id"])
        return redirect(_label_url(example_id, mode))

    @app.get("/label/<path:example_id>")
    def label_record(example_id: str):
        mode = _parse_mode(request.args.get("mode"))
        all_cands = _all_candidates()
        # Validate id against full set; navigate within mode queue.
        try:
            record_index(all_cands, example_id)
        except KeyError:
            abort(404)
        queue = _queue(mode)
        # If current id is outside sample (e.g. deep link), fall back to all order
        # but keep mode flag for toggle UI.
        try:
            idx = record_index(queue, example_id)
            nav = queue
        except KeyError:
            idx = record_index(all_cands, example_id)
            nav = all_cands
        candidate = nav[idx]
        ann = _annotations()
        row = merge_row(candidate, (ann.get("annotations") or {}).get(example_id))
        structure = load_structure_preview(
            str(row["corpus"]),
            str(row.get("source_file") or ""),
            row.get("schutte_nr"),
        )
        soft_n = sum(1 for ln in structure if ln.get("zone") == "soft_break")
        soft_i = 0
        for ln in structure:
            if ln.get("zone") == "soft_break":
                ln["sep_index"] = soft_i
                soft_i += 1
        sep_map = row.get("separators") or {}
        prev_id = str(nav[idx - 1]["example_id"]) if idx > 0 else None
        next_id = str(nav[idx + 1]["example_id"]) if idx + 1 < len(nav) else None
        st = stats(queue if mode == "sample" else all_cands, ann)
        hs = header_summary(all_cands)
        return render_template(
            "label.html",
            row=row,
            structure=structure,
            soft_n=soft_n,
            sep_map=sep_map,
            separator_roles=SEPARATOR_ROLES,
            index=idx,
            prev_id=prev_id,
            next_id=next_id,
            stats=st,
            header_summary=hs,
            verdict=str(row.get("verdict") or "ok"),
            verdicts=VERDICTS,
            state_file=str(annotations_path()),
            mode=mode,
            sample_size=DEFAULT_SAMPLE_SIZE,
        )

    @app.get("/api/stats")
    def api_stats():
        mode = _parse_mode(request.args.get("mode"))
        return jsonify(stats(_queue(mode), _annotations()))

    @app.post("/api/save/<path:example_id>")
    def api_save(example_id: str):
        mode = _parse_mode(request.args.get("mode"))
        all_cands = _all_candidates()
        queue = _queue(mode)
        payload = request.get_json(silent=True) or {}
        try:
            updated = update_annotation(
                _annotations(), example_id, payload, candidates=all_cands
            )
        except KeyError:
            abort(404)
        except ValueError as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400
        path = save_annotations(updated)
        row = merge_row(
            next(c for c in all_cands if str(c["example_id"]) == example_id),
            (updated.get("annotations") or {}).get(example_id),
        )
        return jsonify(
            {
                "ok": True,
                "path": str(path),
                "row": {
                    "verdict": row.get("verdict"),
                    "labelled": row.get("labelled"),
                    "uncertain": row.get("uncertain"),
                },
                "stats": stats(queue, updated),
                "updated_at": updated.get("updated_at"),
            }
        )

    return app


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Schutte lemma structure review UI")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    print("Loading candidates (Excel + persons index + TOC)…")
    cands = _cached_candidates()
    hs = header_summary(list(cands))
    print(
        f"  lemmas={hs['n']}  header pass={hs['pass']} warn={hs['warn']} "
        f"fail={hs['fail']} ({hs['pass_pct']}%)"
    )
    sample = build_review_sample(list(cands), load_annotations())
    print(f"  sample queue={len(sample)} (default mode=sample)")
    print(f"Persisting reviews to {annotations_path()}")
    print(f"Open http://{args.host}:{args.port}/")
    create_app().run(
        host=args.host,
        port=args.port,
        debug=args.debug or bool(os.environ.get("FLASK_DEBUG")),
    )


if __name__ == "__main__":
    main()
