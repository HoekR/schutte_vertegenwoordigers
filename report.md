# Schutte Repertorium — Self-Contained Reference System

## Architecture decision

**Stack: Jinja2 + Pagefind + GitHub Pages, built inside the existing Python project.**

Rationale:
- All code in one language (Python) and one `uv` project
- No server or database — GitHub Pages hosts static HTML for free
- JSON-LD injected in `<head>` of each page: invisible to users, harvestable by search engines and linked-data crawlers
- Pagefind provides full-text search over the built HTML with zero configuration
- VIAF/Wikidata identifiers can be added incrementally as extra fields
- Version-controlled; rebuild triggered automatically by GitHub Actions on push

```
lemma_extractor/           ← existing uv project
├── src/lemma_extractor/
│   ├── parse_html.py      ← Phase 1: parse HTML pages → annotated lines
│   ├── group_lemmas.py    ← Phase 2: group lines → lemma records (using toc)
│   ├── parse_index.py     ← Phase 3: parse personenindex + geoindex
│   ├── build_refs.py      ← Phase 4: assemble cross-reference graph
│   └── export_json.py     ← Phase 4b: write lemmas.json
├── templates/             ← Jinja2 HTML templates
│   ├── base.html
│   ├── lemma.html
│   ├── index.html
│   └── search.html
├── build.py               ← Phase 5: render _site/ from JSON
└── _site/                 ← GitHub Pages root (gitignored locally)
    ├── lemma/nl/5/index.html
    ├── lemma/bl/1/index.html
    ├── search/            ← Pagefind index (built after HTML)
    └── index.html
```

---

## Plan

## Data inventory

| Source | Format | Content | Size |
|---|---|---|---|
| `schutte_binnenland/*.html` | HTML (latin-1) | 221 pages, NL vertegenwoordigers abroad | ~1 MB |
| `schutte_buitenland/*.html` | HTML (latin-1) | 502 pages, foreign reps in NL | ~3 MB |
| `toc_nl.xml` | XML | 342 lemma entries, schutte_nr → page | — |
| `toc_bl.xml` | XML | 686 lemma entries, schutte_nr → page | — |
| `schutte_df.csv` | CSV | Structured metadata per lemma (name, page, nr, category) | — |
| `personen_index_nederland.xml` | text/XML | 4033 name entries, 323 with schuttenr cross-refs | 108 KB |
| `personenindex_buitenland.xml` | text/XML | 8183 name entries, 684 with schuttenr cross-refs | 236 KB |
| `geoindex_nederland.xml` | text/XML | Geographic index with page refs (NL corpus) | — |
| `geoindex_buitenland.xml` | text/XML | Geographic index with page refs (BL corpus) | — |

## What a self-contained reference system looks like

Each lemma becomes a structured object:

```
Lemma
├── id            (schutte_nr)
├── corpus        (nl / bl)
├── name          (from toc / schutte_df)
├── category      (country chapter)
├── page          (source page number)
├── period_header (role/date line immediately before, e.g. "1598-1613 agent")
├── body          (main career narrative, indent 5)
├── genealogy     (family and sources, indent 6-7)
├── sub_notes     (secretaries, staff, indent 9-11)
├── page_footnotes (numbered notes at page bottom, indent 0)
├── inline_refs   (footnote numbers embedded in body text, e.g. "1589¹²")
└── cross_refs    (schuttenr references in personenindex, e.g. "(5) 3, 4, 9")
```

Person index entries link names → lemma ids. The geographic indexes link place names → pages (and thus lemmas). This forms a graph.

---

## Phase 1 — Parse and extract lemmas from HTML

**Goal:** Produce one JSON record per lemma with the structure above.

**Input:** HTML pages in `schutte_binnenland/` and `schutte_buitenland/`  
**Guide:** `toc_nl.xml` / `toc_bl.xml` give the authoritative schutte_nr → page mapping.

### 1a. Parse individual HTML pages into annotated line objects

For each `<br>`-separated line, classify by indentation:

| Indent | Class | Notes |
|---|---|---|
| 0 | `period_header` | matches `^\d{4}` or `^\d{4}-\d{4}` |
| 0 | `footnote_nl` | matches `^\d+[a-z]?\.\s` (binnenland style: `11.   text`) |
| 0 | `footnote_bl` | matches `^\d+[a-z]?\s` (buitenland style: `11 text`) |
| 0 | `chapter_intro` | chapter heading or free intro text — **skip** |
| 0 | `page_number` | bare number + whitespace — **skip** |
| 5 | `body` | main lemma narrative |
| 6–7 | `genealogy` | genealogy and bibliography |
| 9–11 | `sub_note` | secretaries and staff |
| other | `continuation` | wrap-around from previous zone |

A lemma starts at a line matching `^\d+\.\s{3,6}[A-Z]` (at indent 0), which is the schuttenr entry line. The toc gives us which schuttenr starts on which page.

### 1b. Group lines into zones per lemma

Since lemmas may span multiple pages, use the toc mapping to assign page ranges to lemmas. Within a page, lemma boundaries are at entry lines (`N.   Name...`).

### 1c. Extract inline footnote markers

Footnote markers in body text appear as superscript numbers directly attached to words (e.g. `1589¹²`, `15933`, `vastgesteld1`). Pattern: a digit string immediately after a word character, not part of a date (heuristic: preceded by a letter, or followed by a non-digit).

Map inline markers → page_footnote text by number within the page.

---

## Phase 2 — Parse personenindex

**Goal:** Build a lookup: `name → [schutte_nr, ...]` and `schutte_nr → [name, page_refs]`

### 2a. Parse index lines

Format A (binnenland): `Lastname, Firstname (schuttenr) page, page, page`  
Format B (buitenland): same, sometimes with birth year: `Name (schuttenr) (1735-1826) page...`  
Format C: `Name page, page` (no schuttenr — person appears but is not a main entry)

Parse rules:
- Strip XML header line
- `^\s*(.+?)\s+\((\d+)\)\s+([\d,/ ]+)` → name with primary schuttenr
- Remaining page numbers after schuttenr are pages they appear on in other lemmas
- `^\s*(.+?)\s+([\d,/ ]+)$` → name without schuttenr, only page refs

### 2b. Build cross-reference graph

From the parsed index:
- Each schuttenr entry in the index → a node with outgoing page references
- Page references resolve to lemma ids via toc mapping
- This gives: "schuttenr X appears in the text of schuttenr Y, Z, ..."

---

## Phase 3 — Parse geographic indexes

**Goal:** Build a lookup: `place_name → [page_nr, ...]` → `[lemma_id, ...]`

Format: `Placename (page)\nPlacename page` — simple flat index with page numbers.  
Parse with regex `^(.+?)\s+(\d+(?:,\s*\d+)*)$` to get name → page list.

---

## Phase 4 — Assemble the reference system

**Output format:** JSON-LD or plain JSON, one file per corpus or a single combined file.

```json
{
  "lemmas": {
    "nl:5": {
      "id": 5, "corpus": "nl",
      "name": "Aerssen, François van",
      "category": "I. Frankrijk",
      "period": "1598-1613 agent, ordinaris ambassadeur 1609",
      "body": "...",
      "genealogy": "...",
      "sub_notes": [...],
      "footnotes": {"14": "Res. ...", ...},
      "appears_in": ["nl:4", "nl:6", ...],
      "places": ["Parijs", "Nantes"]
    }
  },
  "persons": {
    "Aerssen, François van": {"lemma_id": "nl:5", "appears_on_pages": [3,4,9,61,91]}
  },
  "places": {
    "Parijs": ["nl:1", "nl:2", "nl:5", ...]
  }
}
```

---

## Phase 5 — Verification

Cross-checks to run:
1. Lemma count matches toc: 342 NL, 686 BL
2. Every schuttenr in personenindex with `(N)` resolves to a lemma
3. Every page reference in personenindex falls within a known lemma's page range
4. Inline footnote markers in body text match page_footnote numbers on the same page
5. Geographic page refs resolve to known lemmas

---

## Implementation order

1. `src/lemma_extractor/parse_html.py` — parse HTML pages into annotated line objects
2. `src/lemma_extractor/group_lemmas.py` — group lines into lemma records using toc
3. `src/lemma_extractor/parse_index.py` — parse personenindex and geoindex
4. `src/lemma_extractor/build_refs.py` — assemble cross-reference graph
5. `src/lemma_extractor/export_json.py` — write final JSON output
6. `build.py` — render static HTML site using Jinja2 templates
7. GitHub Actions workflow — auto-build and deploy to GitHub Pages on push

**Check at each phase:** compare counts against toc totals (342 NL, 686 BL).

## Deployment

```yaml
# .github/workflows/build.yml (sketch)
on: [push]
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v4
      - run: uv sync
      - run: uv run lemma-extractor build-site
      - run: npx pagefind --site _site
      - uses: peaceiris/actions-gh-pages@v3
        with:
          github_token: ${{ secrets.GITHUB_TOKEN }}
          publish_dir: ./_site
```

---

## Known issues to handle

- **Encoding:** Both corpora are latin-1. Some pages are double-mangled (from earlier XML conversion) — work directly from HTML, avoid the XML files.
- **Footnote format:** Binnenland uses `N.   text`, buitenland uses `N text` (no dot). Handle both.
- **Chapter intro pages:** First page(s) of each country chapter contain intro text at indent 0 that is not a lemma or footnote. Skip until first lemma entry line.
- **Hyphenation:** Words split at line ends with `-` are OCR artifacts present throughout. Leave as-is (lossless) or optionally rejoin.
- **Inline footnote markers:** Ambiguous — `15933` could be year 1593 + footnote 3, or number 15933. Heuristic needed; flag uncertain cases.
