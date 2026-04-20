# Schutte RNVB — Lemma Extractor & Site Builder

Tools for extracting, enriching, and publishing biographical entries from
G.W. Schutte's *Repertorium der Nederlandse vertegenwoordigers residerende in
het buitenland 1584–1810* (NL) and *Repertorium der buitenlandse vertegenwoordigers
residerende in Nederland 1584–1810* (BL).

---

## Quick start

```bash
# Prerequisites: Python ≥ 3.12, uv
cd lemma_extractor
uv sync

# 1. Tag source XMLs with lemma-start markers
uv run python main.py tag --corpus all

# 2. Extract individual lemma XML files (section-classified, refs linkified)
uv run python main.py extract --corpus all

# 3. Build static website
uv run python build.py

# Preview locally
python3 -m http.server 8000 --directory _site
```

---

## Repository layout

```
lemma_extractor/
  main.py               CLI for tag / extract / verify / assemble steps
  build.py              Static-site builder (HTML → _site/)
  pyproject.toml        uv project config + dependencies
  templates/            Jinja2 templates for the static site
  src/lemma_extractor/  Python package
    assemble_corpus.py  Build a corpus XML from Tesseract hOCR page files
    build_refs.py       Cross-reference enrichment (persons, geo)
    export_json.py      Export enriched data to JSON
    extract_lemmas.py   Split tagged XML into individual lemma XML files
    group_lemmas.py     Group annotated lines into per-lemma records (HTML path)
    linkify_refs.py     Hyperlink N.N.B.W. / Van der Aa citations
    parse_hocr.py       Parse Tesseract hOCR → annotated line objects
    parse_html.py       Parse source HTML pages → annotated line objects
    parse_index.py      Parse persons / geo index XML files
    read_excel.py       Load lemma metadata from Dijkstra Excel workbooks
    tag_xml.py          Insert <start schuttenr="N"> markers into corpus XML
    verify.py           Smoke-test extracted lemma files against Excel metadata

schutte_binnenland/     NL HTML source pages + assembled / tagged corpus XMLs
schutte_buitenland/     BL HTML source pages + assembled / tagged corpus XMLs
schutte_binnenland_ocr/ NL Tesseract hOCR files (221 pages)
schutte_buitenland_ocr/ BL Tesseract hOCR files (502 pages)
lemmas/nl/              Individual lemma XML files, NL corpus (316 files)
lemmas/bl/              Individual lemma XML files, BL corpus (683 files)
dijkstra_bew/           Excel workbooks with lemma metadata (Dijkstra)
_site/                  Generated static website (git-ignored)
```

---

## Two parallel pipelines

### Pipeline A — Static website (`build.py`)

Reads HTML source pages directly via `group_lemmas` → `parse_html`:

```
schutte_binnenland/*.html  ┐
schutte_buitenland/*.html  ├─→ group_lemmas → build_refs → Jinja2 → _site/
toc_nl.xml / toc_bl.xml    ┘
personen_index*.xml
geoindex*.xml
dijkstra_bew/*.xlsx         ──→ metadata / timeline
```

Outputs: `_site/{nl,bl}/NNNN/index.html`, corpus index pages, persons, geo,
timeline, landen (per-country), search, home page, and JSON data exports.

| Page | URL | Description |
|------|-----|-------------|
| Home | `index.html` | Summary counts and links |
| Per land | `landen/index.html` | Book-order country/chapter browse (NL + BL tabs) |
| Zoeken | `search.html` | Client-side filtered search: name, corpus, country, function, period |
| NL index | `nl/index.html` | All NL lemmas sorted by number |
| BL index | `bl/index.html` | All BL lemmas sorted by number |
| Personen | `persons.html` | Combined person register, alphabetical |
| Plaatsen | `geo.html` | Geographic index |
| Functies | `functie.html` | Diplomatic-role register |
| Tijdlijn | `timeline.html` | Interactive JS timeline chart |
| Colofon | `colofon.html` | Credits and sources |
| Lemma | `{nl,bl}/NNNN/index.html` | Individual biography page |

Search uses a compact `data/search_index.json` built at site-build time
(~1 000 records, loaded once, filtered entirely in the browser).

Target URL: `https://[owner].github.io/schutte_vertegenwoordigers/`

### Pipeline B — Lemma XML files (`main.py`)

Produces structured XML with section classification and linkified references:

```
schutte_binnenland/*.html ──→ [pre-built] schutte_binnenland_output_tagged.xml
schutte_buitenland/*.html ──→ tag ──→ schutte_buitenland_output_tagged.xml
dijkstra_bew/*.xlsx        ──→ (metadata for tag + extract)
         ↓
     main.py extract
         ↓
lemmas/nl/nl_NNNN.xml   (316 files)
lemmas/bl/bl_NNNN.xml   (683 files)
```

Each lemma XML carries `<line type="...">` section attributes:

| type | meaning |
|------|---------|
| `loopbaan` | career narrative (default) |
| `personalia` | genealogical block (Zoon van / Dochter van) |
| `bronnen` | bibliographic references — linkified to N.N.B.W. / Van der Aa |
| `noot` | footnotes |
| `hoofd` | sub-entry period heading (e.g. `1749–1768 minister resident`) |
| `paginahoofd` | OCR page-header artefact |

`bronnen` lines receive hyperlinks to the online N.N.B.W. and Van der Aa
encyclopaedias via `linkify_refs.linkify_all()`.

### hOCR assembly (optional, `main.py assemble`)

Assembles a clean UTF-8 corpus XML directly from Tesseract hOCR output,
bypassing the HTML source.  The resulting `*_output_hocr.xml` is **not** used
by the main tag/extract pipeline (the Excel lemma-start strings come from the
HTML text, not from OCR), but is available for text-quality comparison:

```bash
uv run python main.py assemble --corpus all
# → schutte_binnenland/schutte_binnenland_output_hocr.xml  (221 pages, ~9 000 lines)
# → schutte_buitenland/schutte_buitenland_output_hocr.xml  (502 pages, ~21 000 lines)
```

---

## Corpora

| Corpus | Description | Lemmas extracted | Tagging |
|--------|-------------|-----------------|---------|
| NL (`nl`) | Nederlandse vertegenwoordigers in het buitenland 1584–1810 | 316 / 342 | pre-tagged |
| BL (`bl`) | Buitenlandse vertegenwoordigers in Nederland 1584–1810 | 683 / 689 | tagged from `output_raw.xml` |

Not-found schuttenrs in BL: 1, 275, 519, 660 (start lines not matched in source XML).

---

## CLI reference

```
uv run python main.py {assemble|tag|extract|verify|all} [--corpus nl|bl|all] [-v]

  assemble  Build corpus XML from hOCR page files → *_output_hocr.xml
  tag       Insert <start> markers into source XML → *_output_tagged.xml
  extract   Split tagged XML into lemmas/  (section-classified, refs linked)
  verify    Check extracted files against Excel metadata
  all       Run tag → extract → verify  (does NOT include assemble)
```

```
uv run python build.py [--site-dir _site] [--pagefind]

  Builds the full static website from HTML source pages.
  Use --pagefind to run Pagefind indexing after the build (requires pagefind CLI).
```
