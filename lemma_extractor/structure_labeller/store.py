"""Candidates + disk-backed reviews for Schutte lemma structure/header gold.

Mirrors republic_ner ``lumped_paragraph_labeller.store`` / trifecta ``gold_labeller``:
JSON annotations on every save; candidates built from Excel + persons index + TOC.

Verdicts
--------
ok     — header + zone structure look right
issue  — something wrong (describe in note)
skip   — not reviewing / out of scope
"""

from __future__ import annotations

import hashlib
import json
import re
import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from lemma_extractor.name_sim import (
    DEFAULT_NAME_THRESHOLD,
    name_similarity,
    name_similarity_msa,
)
from lemma_extractor.parse_index import parse_persons
from lemma_extractor.read_excel import display_name_from_meta, parse_schutte_nr
from lemma_extractor.structure_checks import apply_structure_checks

# lemma_extractor/ structure_labeller/ → parents[2] = workspace root
PROJECT_ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
DEFAULT_ANNOTATIONS_PATH = HERE / "review" / "structure_reviews.json"

VERDICTS = ("ok", "issue", "skip")
FORMAT = "schutte_structure_reviews_v1"
# Default stratified review set (warn/fail + chapter mix); not the full corpus.
DEFAULT_SAMPLE_SIZE = 50
DEFAULT_SAMPLE_SEED = 42

# Soft whiteline separator roles (exactly one per gap).
SEPARATOR_ROLES = (
    ("before_entry", "before next lemma entry"),
    ("before_period", "before period / role header"),
    ("before_footnote", "before footnote block"),
    ("before_genealogy", "before genealogy / sources"),
    ("page_break", "page break / OCR artefact (ignore)"),
    ("other", "other / unclear"),
)
SEPARATOR_ROLE_IDS = tuple(r[0] for r in SEPARATOR_ROLES)

PERSONS = {
    "nl": PROJECT_ROOT / "personen_index_nederland.xml",
    "bl": PROJECT_ROOT / "personenindex_buitenland.xml",
}
EXCEL = {
    "nl": PROJECT_ROOT / "dijkstra_bew" / "schutte_binnenland_met_lemma.xlsx",
    "bl": PROJECT_ROOT / "dijkstra_bew" / "schutte_buitenland_met_lemma.xlsx",
}
TOC = {
    "nl": PROJECT_ROOT / "toc_nl.xml",
    "bl": PROJECT_ROOT / "toc_bl.xml",
}
HTML_DIRS = {
    "nl": PROJECT_ROOT / "schutte_binnenland",
    "bl": PROJECT_ROOT / "schutte_buitenland",
}


def annotations_path() -> Path:
    return DEFAULT_ANNOTATIONS_PATH


def _sim(a: str, b: str) -> float:
    """FuzzySearcher char/ngram + rapidfuzz Lev + SW/DAG + MSA (see ``name_sim``)."""
    return name_similarity(a, b)


def _strip_nr(title: str) -> str:
    return re.sub(r"^\d+[a-z]?\.\s*", "", title or "").strip()


def _load_toc_titles(corpus: str) -> dict[int, dict[str, Any]]:
    path = TOC[corpus]
    if not path.exists():
        return {}
    root = ET.parse(path).getroot()
    out: dict[int, dict[str, Any]] = {}
    chapter = ""
    for item in root.iter("item"):
        if item.get("level") == "0":
            title_el = item.find("title")
            chapter = (title_el.text or "").strip() if title_el is not None else ""
            continue
        sn = item.get("schutte_nr")
        if not sn:
            continue
        try:
            nr = int(sn)
        except ValueError:
            continue
        title_el = item.find("title")
        page_el = item.find("page")
        # Prefer printed page ``number`` over ``source``: in both TOC files
        # ``source`` is stuck on a single value for nearly all items and does
        # not match HTML file numbers. Book page ≈ HTML ``_NNNN.html``.
        toc_page = 0
        if page_el is not None:
            try:
                toc_page = int(page_el.get("number") or (page_el.text or "0") or "0")
            except ValueError:
                toc_page = 0
        out[nr] = {
            "toc_title": (title_el.text or "").strip() if title_el is not None else "",
            "toc_chapter": chapter,
            "toc_page": toc_page,
            "source_file": f"{toc_page:04d}" if toc_page else "0000",
        }
    return out


def _persons_by_nr(corpus: str) -> dict[int, dict[str, Any]]:
    path = PERSONS[corpus]
    if not path.exists():
        return {}
    by_nr: dict[int, dict[str, Any]] = {}
    for p in parse_persons(path, corpus):
        nr = p.get("schutte_nr")
        if nr is None:
            continue
        # Prefer first subject entry; keep name
        by_nr.setdefault(int(nr), p)
    return by_nr


def _excel_rows(corpus: str) -> dict[Any, dict[str, Any]]:
    path = EXCEL[corpus]
    df = pd.read_excel(path)
    out: dict[Any, dict[str, Any]] = {}
    for _, row in df.iterrows():
        nr = parse_schutte_nr(row.get("schutte_nr"))
        if nr is None:
            continue
        meta = {k: (None if pd.isna(v) else v) for k, v in row.items()}
        meta["display_name"] = display_name_from_meta(meta)
        out[nr] = meta
    return out


def _header_checks(
    *,
    display_name: str,
    toc_title: str,
    persons_name: str | None,
    excel_name: str,
    excel_given: str,
) -> dict[str, Any]:
    toc_plain = _strip_nr(toc_title)
    vs_toc = _sim(display_name, toc_plain)
    vs_persons = _sim(display_name, persons_name or "") if persons_name else 0.0
    # 3-way MSA when Excel + TOC + persons all present (and + pairwise MSA)
    msa_names = [n for n in (display_name, toc_plain, persons_name or "") if n]
    vs_msa = name_similarity_msa(*msa_names) if len(msa_names) >= 2 else 0.0
    # Excel parts present?
    has_name = bool(excel_name)
    has_given = bool(excel_given)
    persons_hit = bool(persons_name)
    thr = DEFAULT_NAME_THRESHOLD
    toc_ok = vs_toc >= thr if toc_plain else False
    persons_ok = (vs_persons >= thr) if persons_hit else None  # None = no index subject
    msa_ok = vs_msa >= thr if len(msa_names) >= 2 else None
    flags: list[str] = []
    if not display_name:
        flags.append("empty_display_name")
    if not has_name:
        flags.append("excel_missing_surname")
    if not toc_ok and toc_plain:
        flags.append("weak_vs_toc")
    if persons_ok is False:
        flags.append("weak_vs_persons_index")
    if persons_hit is False:
        flags.append("no_persons_index_subject")
    status = "pass" if not flags else ("warn" if persons_ok is not False and toc_ok else "fail")
    if flags == ["no_persons_index_subject"] and toc_ok:
        status = "warn"
    return {
        "vs_toc": round(vs_toc, 3),
        "vs_persons": round(vs_persons, 3) if persons_hit else None,
        "vs_msa": round(vs_msa, 3) if len(msa_names) >= 2 else None,
        "persons_hit": persons_hit,
        "toc_ok": toc_ok,
        "persons_ok": persons_ok,
        "msa_ok": msa_ok,
        "flags": flags,
        "status": status,
    }


def load_candidates(*, corpora: tuple[str, ...] = ("nl", "bl")) -> list[dict[str, Any]]:
    """Build one candidate per Excel lemma with header auto-checks."""
    candidates: list[dict[str, Any]] = []
    for corpus in corpora:
        excel = _excel_rows(corpus)
        toc = _load_toc_titles(corpus)
        persons = _persons_by_nr(corpus)
        for nr, meta in sorted(
            excel.items(),
            key=lambda kv: (0, kv[0], "") if isinstance(kv[0], int) else (1, 0, str(kv[0])),
        ):
            # Skip string ids like 418a for TOC/persons int keys — still reviewable
            toc_meta = toc.get(nr) if isinstance(nr, int) else {}
            pers = persons.get(nr) if isinstance(nr, int) else None
            display = str(meta.get("display_name") or "")
            toc_title = str((toc_meta or {}).get("toc_title") or "")
            persons_name = str(pers["name"]) if pers else None
            checks = _header_checks(
                display_name=display,
                toc_title=toc_title,
                persons_name=persons_name,
                excel_name=str(meta.get("name") or ""),
                excel_given=str(meta.get("givenname") or ""),
            )
            # Excel pagenr is the start-page gold; TOC number is fallback.
            excel_page = meta.get("pagenr")
            try:
                excel_page_i = int(excel_page) if excel_page is not None else 0
            except (TypeError, ValueError):
                excel_page_i = 0
            toc_page = (toc_meta or {}).get("toc_page") or 0
            start_page = excel_page_i or int(toc_page or 0)
            example_id = f"{corpus}:{nr}"
            candidates.append(
                {
                    "example_id": example_id,
                    "corpus": corpus,
                    "schutte_nr": nr,
                    "display_name": display,
                    "excel_name": meta.get("name"),
                    "excel_givenname": meta.get("givenname"),
                    "excel_functie": meta.get("schutte_functie"),
                    "excel_begin": meta.get("derived_beginjaar") or meta.get("schutte_beginjaar"),
                    "excel_eind": meta.get("derived_eindjaar") or meta.get("schutte_eindjaar"),
                    "excel_startregel": meta.get("startregel"),
                    "toc_title": toc_title,
                    "toc_chapter": (toc_meta or {}).get("toc_chapter") or "",
                    "toc_page": toc_page,
                    "source_file": f"{start_page:04d}" if start_page else "",
                    "persons_name": persons_name,
                    "persons_pages": (pers or {}).get("pages") or [],
                    "header_checks": checks,
                    "header_status": checks["status"],
                }
            )
    return candidates


def empty_annotations() -> dict[str, Any]:
    return {"format": FORMAT, "updated_at": None, "annotations": {}}


def load_annotations(path: Path | None = None) -> dict[str, Any]:
    p = path or annotations_path()
    if not p.exists():
        return empty_annotations()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return empty_annotations()
    if not isinstance(data, dict):
        return empty_annotations()
    data.setdefault("format", FORMAT)
    data.setdefault("annotations", {})
    if not isinstance(data["annotations"], dict):
        data["annotations"] = {}
    return data


def save_annotations(state: dict[str, Any], path: Path | None = None) -> Path:
    p = path or annotations_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    out = {
        "format": FORMAT,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "annotations": {
            k: normalize_annotation(v)
            for k, v in dict(state.get("annotations") or {}).items()
            if isinstance(v, dict)
        },
    }
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(p)
    return p


def normalize_annotation(row: dict[str, Any]) -> dict[str, Any]:
    verdict = str(row.get("verdict") or "ok")
    if verdict not in VERDICTS:
        verdict = "ok"
    # Map soft_break index (0-based among soft_break lines) → role id
    raw_sep = row.get("separators") or {}
    separators: dict[str, str] = {}
    if isinstance(raw_sep, dict):
        for k, v in raw_sep.items():
            role = str(v)
            if role in SEPARATOR_ROLE_IDS:
                separators[str(k)] = role
    return {
        "verdict": verdict,
        "note": str(row.get("note") or ""),
        "uncertain": bool(row.get("uncertain")),
        "labelled": bool(row.get("labelled", True)),
        "separators": separators,
        "updated_at": row.get("updated_at") or datetime.now(timezone.utc).isoformat(),
    }


def merge_row(candidate: dict[str, Any], ann: dict[str, Any] | None) -> dict[str, Any]:
    row = dict(candidate)
    if ann:
        row.update(normalize_annotation(ann))
    else:
        # Default whole-lemma verdict: ok (option A)
        row.setdefault("verdict", "ok")
        row.setdefault("note", "")
        row.setdefault("uncertain", False)
        row.setdefault("labelled", False)
        row.setdefault("separators", {})
    return row


def record_index(candidates: list[dict[str, Any]], example_id: str) -> int:
    for i, c in enumerate(candidates):
        if str(c["example_id"]) == str(example_id):
            return i
    raise KeyError(example_id)


def next_unlabelled_id(
    candidates: list[dict[str, Any]], ann: dict[str, Any]
) -> str | None:
    labelled = {
        k
        for k, v in (ann.get("annotations") or {}).items()
        if isinstance(v, dict) and v.get("labelled")
    }
    for c in candidates:
        if str(c["example_id"]) not in labelled:
            return str(c["example_id"])
    return None


def _stable_rank(example_id: str, seed: int) -> str:
    """Deterministic order key for stratified sampling."""
    return hashlib.sha1(f"{seed}:{example_id}".encode()).hexdigest()


def build_review_sample(
    candidates: list[dict[str, Any]],
    ann: dict[str, Any] | None = None,
    *,
    size: int = DEFAULT_SAMPLE_SIZE,
    seed: int = DEFAULT_SAMPLE_SEED,
) -> list[dict[str, Any]]:
    """Stratified review set: all header warn/fail + already labelled + chapter mix.

    Target size defaults to ``DEFAULT_SAMPLE_SIZE`` (~50). Grows past that when
    more lemmas are already labelled or more warn/fail rows exist.
    """
    by_id = {str(c["example_id"]): c for c in candidates}
    selected: dict[str, dict[str, Any]] = {}

    for c in candidates:
        if c.get("header_status") in ("warn", "fail"):
            selected[str(c["example_id"])] = c

    if ann:
        for eid, row in (ann.get("annotations") or {}).items():
            if isinstance(row, dict) and row.get("labelled") and eid in by_id:
                selected[eid] = by_id[eid]

    # Stratified fill by (corpus, chapter) round-robin among remaining pass rows.
    pools: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for c in candidates:
        eid = str(c["example_id"])
        if eid in selected:
            continue
        if c.get("header_status") != "pass":
            continue
        key = (str(c.get("corpus") or "?"), str(c.get("toc_chapter") or "?"))
        pools[key].append(c)
    for key in pools:
        pools[key].sort(key=lambda c: _stable_rank(str(c["example_id"]), seed))

    keys = sorted(pools.keys())
    while len(selected) < size and keys:
        progressed = False
        for key in list(keys):
            pool = pools[key]
            if not pool:
                keys.remove(key)
                continue
            c = pool.pop(0)
            selected[str(c["example_id"])] = c
            progressed = True
            if len(selected) >= size:
                break
        if not progressed:
            break

    def _sort_key(c: dict[str, Any]) -> tuple:
        nr = c.get("schutte_nr")
        nr_i = nr if isinstance(nr, int) else 10**9
        return (str(c.get("corpus") or ""), nr_i, str(nr), str(c["example_id"]))

    return sorted(selected.values(), key=_sort_key)


def stats(candidates: list[dict[str, Any]], ann: dict[str, Any]) -> dict[str, int]:
    anns = ann.get("annotations") or {}
    labelled = 0
    by_verdict = {v: 0 for v in VERDICTS}
    header = {"pass": 0, "warn": 0, "fail": 0}
    for c in candidates:
        header[str(c.get("header_status") or "fail")] = (
            header.get(str(c.get("header_status") or "fail"), 0) + 1
        )
        a = anns.get(str(c["example_id"]))
        if isinstance(a, dict) and a.get("labelled"):
            labelled += 1
            v = str(a.get("verdict") or "skip")
            if v in by_verdict:
                by_verdict[v] += 1
    return {
        "total": len(candidates),
        "labelled": labelled,
        "pending": len(candidates) - labelled,
        **{f"verdict_{k}": v for k, v in by_verdict.items()},
        **{f"header_{k}": v for k, v in header.items()},
    }


def update_annotation(
    state: dict[str, Any],
    example_id: str,
    payload: dict[str, Any],
    *,
    candidates: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if candidates is not None:
        record_index(candidates, example_id)  # KeyError if unknown
    verdict = str(payload.get("verdict") or "ok")
    if verdict not in VERDICTS:
        raise ValueError(f"verdict must be one of {VERDICTS}")
    raw_sep = payload.get("separators") or {}
    separators: dict[str, str] = {}
    if isinstance(raw_sep, dict):
        for k, v in raw_sep.items():
            role = str(v)
            if role and role not in SEPARATOR_ROLE_IDS:
                raise ValueError(f"unknown separator role: {role}")
            if role:
                separators[str(k)] = role
    row = normalize_annotation(
        {
            "verdict": verdict,
            "note": payload.get("note") or "",
            "uncertain": bool(payload.get("uncertain")),
            "labelled": True,
            "separators": separators,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    state = dict(state)
    anns = dict(state.get("annotations") or {})
    anns[str(example_id)] = row
    state["annotations"] = anns
    return state


def load_structure_preview(corpus: str, source_file: str, schutte_nr: Any) -> list[dict[str, Any]]:
    """Return zoned lines for one lemma, **keeping blank lines as soft separators**.

    Zones include entry / body / genealogy / sub_note / footnote / period_header /
    blank (rendered as a soft break in the UI). Truncated for display.

    Each line includes:
    - ``line_no`` — 1-based index within this lemma preview
    - ``page_line`` — 1-based line index within the HTML page parse
    - ``page`` — HTML file number (e.g. 1 for ``_0001.html``)
    """
    if not source_file:
        return []
    html_dir = HTML_DIRS.get(corpus)
    if html_dir is None:
        return []
    try:
        from lemma_extractor.group_lemmas import _hocr_for_html
        from lemma_extractor.parse_html import parse_page
        from lemma_extractor.zone_correct import correct_html_zones
    except ImportError:
        return []

    pattern = (
        "schutte_nederlandsevertegenwoordigersinbuitenland_*.html"
        if corpus == "nl"
        else "schutte_buitenlandsevertegenwoordigersinnederland_*.html"
    )
    try:
        start = int(source_file)
    except ValueError:
        return []

    # Compare entry numbers as int when possible
    try:
        want_nr = int(schutte_nr) if not isinstance(schutte_nr, int) else schutte_nr
    except (TypeError, ValueError):
        want_nr = schutte_nr

    lines_out: list[dict[str, Any]] = []
    collecting = False
    keep_zones = {
        "body",
        "genealogy",
        "sub_note",
        "footnote",
        "period_header",
        # Next period head after a lemma (e.g. bl:240 ``(1684)-1698 agent``)
        "chapter_intro",
        "blank",
    }

    def _entry_nr(zone: str, text: str) -> int | None:
        """Schutte lemma nr if this line starts a new entry.

        Some first lines are still zoned ``body`` (HTML indent miss); accept
        ``N.`` on body when N is the lemma we want. Stop only on a true
        ``lemma_entry`` (or body with the *next* consecutive nr) so footnote
        digits like ``25.`` do not truncate the preview.
        """
        m_nr = re.match(r"^(\d+)\.\s", text)
        if not m_nr:
            return None
        nr = int(m_nr.group(1))
        if zone == "lemma_entry":
            return nr
        # Mis-zoned entry line for *this* lemma
        if zone == "body" and nr == want_nr:
            return nr
        # Next lemma also mis-zoned as body (consecutive Schutte nrs)
        if collecting and zone == "body" and isinstance(want_nr, int) and nr == want_nr + 1:
            return nr
        return None

    def _append(zone: str, text: str, *, page: int, page_line: int, src: dict | None = None) -> None:
        row: dict[str, Any] = {
            "zone": zone,
            "text": text,
            "page": page,
            "page_line": page_line,
            "line_no": len(lines_out) + 1,
        }
        if src:
            for key in ("bio_cues", "zone_reason", "zone_orig", "y_frac"):
                if key in src:
                    row[key] = src[key]
        lines_out.append(row)

    for path in sorted(html_dir.glob(pattern)):
        m = re.search(r"_(\d+)\.html$", path.name)
        if not m:
            continue
        file_nr = int(m.group(1))
        if file_nr < start:
            continue
        # Allow a wider window: some HTML files are missing in the sequence
        if file_nr > start + 8:
            break
        hocr = _hocr_for_html(path)
        if hocr.exists():
            page_lines = correct_html_zones(path, hocr, corpus)
        else:
            page_lines = apply_structure_checks(
                [dict(ln) for ln in parse_page(path, corpus)]
            )
        for page_i, ln in enumerate(page_lines, start=1):
            zone = ln.get("zone") or ""
            text = ln.get("text") or ""
            nr = _entry_nr(zone, text)
            if nr is not None:
                if nr == want_nr:
                    collecting = True
                    _append("entry", text, page=file_nr, page_line=page_i, src=ln)
                    continue
                if collecting and nr != want_nr:
                    return lines_out[:60]
            if collecting and zone in keep_zones:
                disp = (
                    "soft_break"
                    if zone == "blank"
                    else ("period_header" if zone == "chapter_intro" else zone)
                )
                _append(
                    disp,
                    text,
                    page=file_nr,
                    page_line=page_i,
                    src=ln,
                )
                if len(lines_out) >= 60:
                    break
            if len(lines_out) >= 60:
                break
    # Re-run block repairs on the lemma stream so genealogy/footnotes that
    # cross HTML page boundaries are corrected (per-page zone_correct cannot).
    repaired = apply_structure_checks(lines_out[:60])
    for i, ln in enumerate(repaired, start=1):
        ln["line_no"] = i
    return repaired


def header_summary(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate auto header-check rates for CLI / progress bar."""
    n = len(candidates) or 1
    counts = {"pass": 0, "warn": 0, "fail": 0}
    for c in candidates:
        counts[str(c.get("header_status") or "fail")] += 1
    return {
        "n": len(candidates),
        "pass": counts["pass"],
        "warn": counts["warn"],
        "fail": counts["fail"],
        "pass_pct": round(100.0 * counts["pass"] / n, 1),
    }
