"""
build.py — Jinja2 static-site builder for the Schutte Repertorium.

Usage (from inside lemma_extractor/):
    .venv/bin/python build.py [--site-dir _site] [--pagefind]

After building, preview with:
    python3 -m http.server 8000 --directory _site
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import xml.etree.ElementTree as ET

import pandas as pd
from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup, escape as html_escape
import pyphen as _pyphen_mod

_PYPHEN = _pyphen_mod.Pyphen(lang="nl_NL")

# ---------------------------------------------------------------------------
# Paths (all relative to this script's directory)
# ---------------------------------------------------------------------------
HERE = Path(__file__).parent          # lemma_extractor/
ROOT = HERE.parent                    # workspace root (schutte-bewerkingen/)
TEMPLATES_DIR = HERE / "templates"

NL_HTML_DIR = ROOT / "schutte_binnenland"
BL_HTML_DIR = ROOT / "schutte_buitenland"
TOC_NL = ROOT / "toc_nl.xml"
TOC_BL = ROOT / "toc_bl.xml"
PERSONS_NL = ROOT / "personen_index_nederland.xml"
PERSONS_BL = ROOT / "personenindex_buitenland.xml"
GEO_NL = ROOT / "geoindex_nederland.xml"
GEO_BL = ROOT / "geoindex_buitenland.xml"
DIJKSTRA_NL = ROOT / "dijkstra_bew" / "schutte_binnenland_met_lemma.xlsx"
DIJKSTRA_BL = ROOT / "dijkstra_bew" / "schutte_buitenland_met_lemma.xlsx"
LEMMAS_NL = ROOT / "lemmas" / "nl"
LEMMAS_BL = ROOT / "lemmas" / "bl"

# Corpus display labels
CORPUS_LABELS = {
    "nl": "Nederlandse vertegenwoordigers in het buitenland",
    "bl": "Buitenlandse vertegenwoordigers in Nederland",
}


# ---------------------------------------------------------------------------
# Metadata helpers
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Enriched lemma XML reader
# ---------------------------------------------------------------------------

# Map <line type="..."> to HTML zone class names used in the templates
_XML_TYPE_TO_ZONE: dict[str, str] = {
    "loopbaan":    "body",
    "personalia":  "genealogy",
    "bronnen":     "bronnen",
    "hoofd":       "period_header",
    # noot and paginahoofd are handled separately (not emitted as lines)
}

_FOOTNOTE_NL_RE = re.compile(r"^(\d+[a-z]?)\.\s{2,}(.+)")
_FOOTNOTE_BL_RE = re.compile(r"^(\d+[a-z]?)\s([A-Z].+)")


def _load_lemma_xml(xml_path: Path, corpus: str) -> tuple[list[dict], dict] | None:
    """Parse a classified lemma XML and return (lines, footnotes), or None on error."""
    try:
        tree = ET.parse(xml_path)
    except ET.ParseError:
        return None

    root = tree.getroot()
    lines: list[dict] = []
    footnotes: dict[str, str] = {}

    for line_el in root.findall("line"):
        ltype = line_el.get("type", "loopbaan")

        if ltype == "paginahoofd":
            continue

        if ltype == "noot":
            # Reconstruct full text from element (no child tags in noot lines)
            text = (line_el.text or "").strip()
            m = _FOOTNOTE_NL_RE.match(text)
            if not m and corpus == "bl":
                m = _FOOTNOTE_BL_RE.match(text)
            if m:
                footnotes[m.group(1)] = m.group(2).strip()
            continue

        zone = _XML_TYPE_TO_ZONE.get(ltype, "body")

        if ltype == "bronnen":
            # Inner content already contains <a> tags; get raw XML text
            # ET.tostring re-escapes & → &amp; which is correct for HTML hrefs
            raw = ET.tostring(line_el, encoding="unicode")
            # strip outer <line ...> ... </line> wrapper
            inner = raw.split(">", 1)[1].rsplit("</line>", 1)[0]
            lines.append({"zone": zone, "text": inner, "pre_html": True})
        else:
            text = (line_el.text or "").strip()
            lines.append({"zone": zone, "text": text, "pre_html": False})

    return lines, footnotes


def _overlay_enriched_lines(lemma: dict, lemmas_dir: Path) -> None:
    """Replace lemma lines and footnotes with data from the classified XML file."""
    corpus = lemma["corpus"]
    nr = lemma["schutte_nr"]
    prefix = corpus
    xml_path = lemmas_dir / f"{prefix}_{nr:04d}.xml"
    if not xml_path.exists():
        return
    result = _load_lemma_xml(xml_path, corpus)
    if result is None:
        return
    xml_lines, xml_footnotes = result
    if xml_lines:
        lemma["lines"] = xml_lines
    if xml_footnotes:
        lemma["footnotes"] = xml_footnotes


def _load_metadata() -> dict:
    """Load Dijkstra Excel files and return {(corpus, schutte_nr): row_dict}."""
    lookup: dict = {}
    for path, corpus in [(DIJKSTRA_NL, "nl"), (DIJKSTRA_BL, "bl")]:
        df = pd.read_excel(path)
        for _, row in df.iterrows():
            raw_nr = row.get("schutte_nr")
            if pd.notna(raw_nr):
                try:
                    nr = int(raw_nr)
                except (ValueError, TypeError):
                    continue
                lookup[(corpus, nr)] = {k: (None if pd.isna(v) else v)
                                        for k, v in row.items()}
    return lookup


def _build_functie_index(meta_lookup: dict) -> list[dict]:
    """Build a function/title index from the Excel metadata.

    Splits composite ``schutte_functie`` values (e.g. 'zonder rang, ambassadeur
    1592, gedeputeerde 1607') into individual roles and groups persons under
    each normalised role label.  Returns a list sorted alphabetically by role.
    """
    from collections import defaultdict, Counter as _Counter

    _YEAR_RE = re.compile(r"\b1[0-9]{3}\.?\b")

    functie_map: dict[str, list] = defaultdict(list)

    for (corpus, nr), meta in meta_lookup.items():
        raw = meta.get("schutte_functie")
        if not raw:
            continue

        # Build readable name
        name_parts = [meta.get("givenname"), meta.get("Intraposition"), meta.get("name")]
        name = " ".join(p for p in name_parts if p)

        def _to_int(v):
            if v is None:
                return None
            try:
                return int(float(str(v)))
            except (ValueError, TypeError):
                return None

        begin = _to_int(meta.get("derived_beginjaar") or meta.get("schutte_beginjaar"))
        end   = _to_int(meta.get("derived_eindjaar")  or meta.get("schutte_eindjaar"))
        category = str(meta.get("category") or "")

        for chunk in re.split(r"[,;]", str(raw)):
            chunk = _YEAR_RE.sub("", chunk).strip().rstrip(" -").strip()
            if not chunk:
                continue
            key = chunk.lower()
            functie_map[key].append({
                "name":            name,
                "nr":              nr,
                "corpus":          corpus,
                "begin":           begin,
                "end":             end,
                "category":        category,
                "functie_display": chunk,
            })

    result = []
    for key in sorted(functie_map.keys()):
        persons = sorted(functie_map[key],
                         key=lambda p: (p["begin"] or 9999, p["nr"]))
        display = _Counter(p["functie_display"] for p in persons).most_common(1)[0][0]
        result.append({
            "functie": display,
            "key":     key,
            "count":   len(persons),
            "persons": persons,
        })
    return result


def _build_timeline_data(meta_lookup: dict, title_lookup: dict) -> list[dict]:
    """Return list of dicts suitable for the JS timeline chart."""
    rows = []
    for (corpus, nr), meta in meta_lookup.items():
        raw_start = meta.get("derived_beginjaar") or meta.get("schutte_beginjaar")
        raw_end   = meta.get("derived_eindjaar")  or meta.get("schutte_eindjaar")
        if raw_start is None:
            continue
        try:
            start = int(raw_start)
            end   = int(raw_end) if raw_end else None
        except (ValueError, TypeError):
            continue
        name = title_lookup.get((corpus, nr), f'{meta.get("name", "")}')
        rows.append({
            "corpus":   corpus,
            "nr":       nr,
            "name":     name,
            "start":    start,
            "end":      end,
            "category": meta.get("category") or "",
            "functie":  str(meta.get("schutte_functie") or ""),
        })
    rows.sort(key=lambda r: (r["corpus"], r["category"], r["start"]))
    return rows


# ---------------------------------------------------------------------------
# Inline markup helpers
# ---------------------------------------------------------------------------

def _join_hyphen(prev_text: str, next_text: str) -> str:
    """Join two lines where prev_text ends with '-'.

    Rules:
    1. If the word after the hyphen starts with an uppercase letter it is a
       genuine compound (Noord-Holland, Sint-Oedenrode) — keep the hyphen.
    2. Otherwise ask pyphen whether the join point is a valid syllable break
       in the reconstructed word.  If yes → remove hyphen (line-wrap).
       If not → keep hyphen (true compound or unknown word).
    """
    stem = prev_text[:-1]          # strip trailing '-'
    first_word_next = next_text.split()[0] if next_text else ""
    if not first_word_next:
        return prev_text + " " + next_text

    # Rule 1: uppercase continuation = real compound hyphen
    if first_word_next[0].isupper():
        return prev_text + " " + next_text

    # Rule 2: check pyphen
    candidate = stem.split()[-1] + first_word_next  # last token of prev + first of next
    join_pos   = len(stem.split()[-1])
    if join_pos in _PYPHEN.positions(candidate):
        # valid syllable break → this was a line-wrap hyphen → remove it
        rest = next_text[len(first_word_next):]
        return stem + first_word_next + rest
    else:
        # not a syllable break → keep hyphen (true compound or name)
        return prev_text + " " + next_text


def _group_lines(lines: list[dict]) -> list[dict]:
    """Group consecutive same-zone lines into a single text block.

    Lines ending with a hyphen (word-break) are joined directly to the next
    line (same zone) without a space, reconstructing the original word.
    pre_html lines are never merged with other lines.
    """
    blocks: list[dict] = []
    for ln in lines:
        pre = ln.get("pre_html", False)
        if (blocks and blocks[-1]["zone"] == ln["zone"]
                and not pre and not blocks[-1].get("pre_html")):
            prev = blocks[-1]["text"]
            if prev.endswith("-"):
                blocks[-1]["text"] = _join_hyphen(prev, ln["text"])
            else:
                blocks[-1]["text"] = prev + " " + ln["text"]
        else:
            blocks.append({"zone": ln["zone"], "text": ln["text"], "pre_html": pre})
    return blocks


def _inline_markup(text: str, corpus: str, root: str, footnotes: dict) -> Markup:
    """Escape text and insert hyperlinks for nr. refs and footnote markers."""
    s = str(html_escape(text))

    # 1. "(zie sub nr. N)" and "nr. N" → hyperlinks
    def repl_nr(m: re.Match) -> str:
        prefix = m.group(1) or ""
        nr = int(m.group(2))
        link = (f'<a href="{root}{corpus}/{nr:04d}/index.html"'
                f' title="Ga naar lemma {nr}">nr.\u00a0{nr}</a>')
        return f"zie sub {link}" if prefix else link

    s = re.sub(r"(zie sub\s+)?nr\.\s*(\d+)", repl_nr, s)

    # 2. Footnote markers: digit(s) appearing immediately after a word character
    #    (no intervening space) to avoid false matches inside dates.
    if footnotes:
        for key in sorted(footnotes.keys(), key=lambda k: len(str(k)), reverse=True):
            ks = str(key)
            s = re.sub(
                rf"(?<=[a-zA-Z\u00C0-\u017E']){re.escape(ks)}(?![\da-zA-Z])",
                f'<sup><a href="#fn-{ks}" id="ref-{ks}">{ks}</a></sup>',
                s,
            )
    return Markup(s)


# ---------------------------------------------------------------------------
# Jinja2 environment
# ---------------------------------------------------------------------------

def _make_env() -> Environment:
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=select_autoescape(["html"]),
    )
    return env


# ---------------------------------------------------------------------------
# Helper: build title lookup for cross-reference rendering
# ---------------------------------------------------------------------------

def _build_title_lookup(lemmas: list[dict]) -> dict[tuple[str, int], str]:
    """Return {(corpus, schutte_nr): toc_title}."""
    return {(l["corpus"], l["schutte_nr"]): l.get("toc_title", f"Nr. {l['schutte_nr']}") for l in lemmas}


# ---------------------------------------------------------------------------
# Render helpers
# ---------------------------------------------------------------------------

def _root_url() -> str:
    """Return the base URL for GitHub Pages."""
    return "/schutte_vertegenwoordigers/"


def _render_lemma(tpl, lemma: dict, site_dir: Path, title_lookup: dict,
                  meta_lookup: dict) -> None:
    corpus = lemma["corpus"]
    nr = lemma["schutte_nr"]
    slug = f"{nr:04d}"
    out_path = site_dir / corpus / slug / "index.html"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    def ref_title(c: str, n: int) -> str:
        return title_lookup.get((c, n), f"Nr. {n}")

    root = _root_url()
    footnotes = lemma.get("footnotes") or {}
    blocks = _group_lines(lemma.get("lines") or [])
    for block in blocks:
        if block.get("pre_html"):
            block["html_text"] = Markup(block["text"])
        else:
            block["html_text"] = _inline_markup(block["text"], corpus, root, footnotes)

    html = tpl.render(
        lemma=lemma,
        root=root,
        corpus=corpus,
        corpus_label=CORPUS_LABELS[corpus],
        prev_nr=lemma.get("_prev_nr"),
        next_nr=lemma.get("_next_nr"),
        ref_title=ref_title,
        blocks=blocks,
        meta=meta_lookup.get((corpus, nr)),
    )
    out_path.write_text(html, encoding="utf-8")


def _add_prev_next(lemmas: list[dict]) -> None:
    """Attach ``_prev_nr`` and ``_next_nr`` to each lemma (sorted by schutte_nr)."""
    sorted_lemmas = sorted(lemmas, key=lambda l: l["schutte_nr"])
    for i, lemma in enumerate(sorted_lemmas):
        lemma["_prev_nr"] = sorted_lemmas[i - 1]["schutte_nr"] if i > 0 else None
        lemma["_next_nr"] = sorted_lemmas[i + 1]["schutte_nr"] if i < len(sorted_lemmas) - 1 else None


# ---------------------------------------------------------------------------
# Main build
# ---------------------------------------------------------------------------

def build(site_dir: Path, run_pagefind: bool = False) -> None:
    # Lazy import so the script is importable without the venv being active
    # (helpful for editors / linters).
    sys.path.insert(0, str(HERE / "src"))
    from lemma_extractor.group_lemmas import group_lemmas
    from lemma_extractor.parse_index import parse_persons, parse_geo
    from lemma_extractor.build_refs import build_refs
    from lemma_extractor.export_json import export

    print("Parsing HTML corpus…")
    nl_lemmas = group_lemmas(NL_HTML_DIR, TOC_NL, "nl")
    bl_lemmas = group_lemmas(BL_HTML_DIR, TOC_BL, "bl")
    print(f"  NL: {len(nl_lemmas)} lemmas, BL: {len(bl_lemmas)} lemmas")

    print("Overlaying enriched lemma XML lines…")
    for lemma in nl_lemmas:
        _overlay_enriched_lines(lemma, LEMMAS_NL)
    for lemma in bl_lemmas:
        _overlay_enriched_lines(lemma, LEMMAS_BL)
    print("  Done.")

    print("Parsing indexes…")
    nl_persons = parse_persons(PERSONS_NL, "nl")
    bl_persons = parse_persons(PERSONS_BL, "bl")
    nl_geo = parse_geo(GEO_NL, "nl")
    bl_geo = parse_geo(GEO_BL, "bl")
    print(f"  Persons NL: {len(nl_persons)}, BL: {len(bl_persons)}")
    print(f"  Geo NL: {len(nl_geo)}, BL: {len(bl_geo)}")

    print("Building cross-references…")
    nl_lemmas, bl_lemmas, persons_index, geo_index = build_refs(
        nl_lemmas, bl_lemmas, nl_persons, bl_persons, nl_geo, bl_geo
    )

    # Prepare output directory
    if site_dir.exists():
        shutil.rmtree(site_dir)
    site_dir.mkdir(parents=True)

    print(f"Exporting JSON to {site_dir / 'data'}…")
    export(nl_lemmas, bl_lemmas, persons_index, geo_index, site_dir / "data")

    env = _make_env()
    title_lookup = _build_title_lookup(nl_lemmas + bl_lemmas)

    # ------------------------------------------------------------------
    # Per-lemma pages
    # ------------------------------------------------------------------
    lemma_tpl = env.get_template("lemma.html")

    _add_prev_next(nl_lemmas)
    _add_prev_next(bl_lemmas)

    print("Loading Excel metadata…")
    meta_lookup = _load_metadata()
    print(f"  Metadata entries: {len(meta_lookup)}")

    print("Rendering NL lemma pages…")
    for lemma in nl_lemmas:
        _render_lemma(lemma_tpl, lemma, site_dir, title_lookup, meta_lookup)

    print("Rendering BL lemma pages…")
    for lemma in bl_lemmas:
        _render_lemma(lemma_tpl, lemma, site_dir, title_lookup, meta_lookup)

    # ------------------------------------------------------------------
    # Corpus index pages
    # ------------------------------------------------------------------
    corpus_idx_tpl = env.get_template("corpus_index.html")

    for corpus, lemmas in [("nl", nl_lemmas), ("bl", bl_lemmas)]:
        sorted_lemmas = sorted(lemmas, key=lambda l: l["schutte_nr"])
        out = site_dir / corpus / "index.html"
        out.write_text(
            corpus_idx_tpl.render(
                corpus=corpus,
                corpus_label=CORPUS_LABELS[corpus],
                lemmas=sorted_lemmas,
                root=_root_url(),
            ),
            encoding="utf-8",
        )
    print("Corpus index pages written.")

    # ------------------------------------------------------------------
    # Persons page
    # ------------------------------------------------------------------
    persons_tpl = env.get_template("persons.html")
    sorted_persons = sorted(persons_index, key=lambda p: p["name"])
    (site_dir / "persons.html").write_text(
        persons_tpl.render(
            persons=sorted_persons,
            root=_root_url(),
        ),
        encoding="utf-8",
    )
    print(f"Persons page written ({len(sorted_persons)} entries).")

    # ------------------------------------------------------------------
    # Geo page
    # ------------------------------------------------------------------
    geo_tpl = env.get_template("geo.html")
    sorted_geo = sorted(geo_index, key=lambda g: g["place"])
    (site_dir / "geo.html").write_text(
        geo_tpl.render(
            places=sorted_geo,
            root=_root_url(),
        ),
        encoding="utf-8",
    )
    print(f"Geo page written ({len(sorted_geo)} entries).")

    # ------------------------------------------------------------------
    # Home page
    # ------------------------------------------------------------------
    home_tpl = env.get_template("index.html")
    (site_dir / "index.html").write_text(
        home_tpl.render(
            root=_root_url(),
            nl_count=len(nl_lemmas),
            bl_count=len(bl_lemmas),
            persons_count=len(persons_index),
            geo_count=len(geo_index),
        ),
        encoding="utf-8",
    )
    print("Home page written.")

    # ------------------------------------------------------------------
    # Timeline page
    # ------------------------------------------------------------------
    timeline_tpl = env.get_template("timeline.html")
    timeline_data = _build_timeline_data(meta_lookup, title_lookup)
    (site_dir / "timeline.html").write_text(
        timeline_tpl.render(
            root=_root_url(),
            timeline_data=timeline_data,
        ),
        encoding="utf-8",
    )
    print(f"Timeline page written ({len(timeline_data)} entries).")

    # ------------------------------------------------------------------
    # Functie index page
    # ------------------------------------------------------------------
    print("Building functie index…")
    functie_index = _build_functie_index(meta_lookup)
    functie_tpl = env.get_template("functie.html")
    (site_dir / "functie.html").write_text(
        functie_tpl.render(
            functies=functie_index,
            root=_root_url(),
        ),
        encoding="utf-8",
    )
    print(f"Functie page written ({len(functie_index)} functies).")

    # ------------------------------------------------------------------
    # Colofon page
    # ------------------------------------------------------------------
    colofon_tpl = env.get_template("colofon.html")
    (site_dir / "colofon.html").write_text(
        colofon_tpl.render(root=_root_url()),
        encoding="utf-8",
    )
    print("Colofon page written.")

    # ------------------------------------------------------------------
    # Optional: Pagefind
    # ------------------------------------------------------------------
    if run_pagefind:
        _run_pagefind(site_dir)

    print(f"\nDone! Site is in {site_dir}")
    print(f"Preview: python3 -m http.server 8000 --directory {site_dir}")


def _run_pagefind(site_dir: Path) -> None:
    print("Running Pagefind…")
    cmd = ["npx", "pagefind", "--site", str(site_dir)]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print("Pagefind error:", result.stderr, file=sys.stderr)
    else:
        print(result.stdout)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Build Schutte Repertorium static site")
    parser.add_argument(
        "--site-dir",
        default="_site",
        help="Output directory for the site (default: _site)",
    )
    parser.add_argument(
        "--pagefind",
        action="store_true",
        help="Run Pagefind after building (requires npx/pagefind)",
    )
    args = parser.parse_args()
    build(Path(args.site_dir), run_pagefind=args.pagefind)


if __name__ == "__main__":
    main()
