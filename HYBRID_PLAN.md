# Hybrid engine plan

Hand each task to the engine that is best at it. HTML stays the canonical text source for the site; other engines correct or enrich it.

## Engines

| Engine | Owns | Does not own |
|--------|------|--------------|
| **HTML** (`parse_html` / `group_lemmas` / `build`) | Canonical lemma text, site build | Reliable entry vs footnote when indent=0 |
| **Tesseract hOCR** (`parse_hocr`) | Layout zones via bbox (x-indent, later y for page-bottom notes) | Font style; primary text |
| **PDF** (ABBYY / notebook) | Italic / bold / digit style cues | Lemma grouping |
| **Excel** (`dijkstra_bew`) | `naam`, `functie`, Schutte nr, start page/line | Body text |
| **LLM** (`parse_lemmas_instructor`) | Structured enrichment (bio slots, related, notes) | Zone fixes; critical-path site |

## Steps

### 1 — Align & audit HTML ↔ hOCR zones
Compare classified lines on matched pages. Quantify disagreements, especially `lemma_entry` ↔ `footnote` and missing first lines. Deliverable: audit script + disagreement report on a sample (then full corpora).

### 2 — hOCR-assisted zone correction ✅
Where HTML and hOCR disagree on entry vs footnote, prefer bbox **y** (page-bottom band ≈ `y_frac ≥ 0.78` → footnote), plus note-wording cues (`verbaal` / `Res.` / …).

- `parse_hocr.py` — full bbox; y-aware entry/footnote resolve
- `zone_correct.py` — `correct_html_zones()` keeps HTML text, overlays zone from aligned hOCR y
- `group_lemmas.py` — uses correction by default (`use_hocr_zones=True`)
- Audit: `uv run python audit_html_hocr_zones.py --corrections --pages 30`

Checked: BL lemma 9 (Charnacé) goes from 0 lines → 23 with correction on.

### 3 — PDF style overlay ✅
Align PDF page to HTML via `PDF_OFFSET`. Attach italic/bold spans (names, period headers, italic footnote digits) for display.

- `pdf_style.py` — extract from `pdf_sourcs/schuttepdfs.tar.gz` (cached); overlay spans onto HTML lines
- `group_lemmas(..., use_pdf_style=True)` — attaches `style_spans` / `italic_digits`
- `build.py` — renders `<i>` / `<b>` via `_inline_markup`

Checked: BL page 7 → bold period years, italic person names, italic digit `2` on Charnacé.

### 4 — Excel-driven lemma headers ✅
Site lemma header from Dijkstra metadata (`display_name`, `schutte_functie`, Schutte nr). Keep the printed entry line in the body (`.zone-entry`).

- `read_excel.display_name_from_meta()` — `Surname, Givenname [intra] [post]`
- `_load_metadata()` adds `display_name` on each row
- `templates/lemma.html` — header from Excel; no HTML `period_header` in the title strip
- Entry line remains the first body block (not used as the page title)

### 5 — LLM enrichment (deferred)
Skipped for now — local LM Studio / `gpt-oss-20b` timed out on structured output; not needed for the site layout path. Revisit later (SURF or a faster local model) if structured bio enrichment is wanted.

### Structure gold UI ✅ → checks in pipeline
Flask labeller for zone gold (sample ~50). Enough gold collected; rules folded into code:

- ``structure_checks.py`` — genealogy only from `Zoon/Dochter/Uit dit huwelijk` in contiguous blocks; footnote gap-fill (no body↔fn flicker); `bio_cues` for `geb.` / baptism `ged.` / `birth_continued` (year/month on next line) / death cross `f`/`t`
- Wired at end of ``zone_correct.correct_html_zones`` (and HTML-only path)
- Header match: ``name_sim.name_similarity`` = FuzzySearcher char/ngram + rapidfuzz classic Lev (raw + token-sorted) **and** formulation-style Lev+SW/DAG **and** pairwise NW MSA (`name_align`). 3-way via ``name_similarity_msa`` / ``vs_msa``. fuzzy-search 3.x indel Lev rejected (FP).

```bash
cd lemma_extractor
uv sync --extra review
uv run schutte-structure-ui
# http://127.0.0.1:5080
```

### Follow-ups (optional)
- LLM enrichment (step 5) — still deferred
- NL tagged XML still omits many HTML pages (only 0008/0202 backfilled for lemmas 7/167); fuller re-assembly optional

## Non-goals
- Replacing HTML with hOCR as the site source text
- Running the LLM to fix first-line / footnote bugs
- Full PAGE-XML conversion unless hOCR bbox proves insufficient
