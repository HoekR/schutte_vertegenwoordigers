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
import shutil
import subprocess
import sys
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

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

# Corpus display labels
CORPUS_LABELS = {
    "nl": "Nederlandse vertegenwoordigers in het buitenland",
    "bl": "Buitenlandse vertegenwoordigers in Nederland",
}


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


def _render_lemma(tpl, lemma: dict, site_dir: Path, title_lookup: dict) -> None:
    corpus = lemma["corpus"]
    nr = lemma["schutte_nr"]
    slug = f"{nr:04d}"
    out_path = site_dir / corpus / slug / "index.html"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    def ref_title(c: str, n: int) -> str:
        return title_lookup.get((c, n), f"Nr. {n}")

    # Determine prev/next using the sorted position stored during batch render
    html = tpl.render(
        lemma=lemma,
        root=_root_url(),
        corpus=corpus,
        corpus_label=CORPUS_LABELS[corpus],
        prev_nr=lemma.get("_prev_nr"),
        next_nr=lemma.get("_next_nr"),
        ref_title=ref_title,
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

    print("Rendering NL lemma pages…")
    for lemma in nl_lemmas:
        _render_lemma(lemma_tpl, lemma, site_dir, title_lookup)

    print("Rendering BL lemma pages…")
    for lemma in bl_lemmas:
        _render_lemma(lemma_tpl, lemma, site_dir, title_lookup)

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
