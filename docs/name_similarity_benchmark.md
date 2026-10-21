# Name similarity benchmark — Schutte headers

**Date:** 2026-10-21  
**Question:** How should Excel `display_name` be matched to TOC / persons-index titles?  
**Constraint:** Prefer Marijn Koolen’s `fuzzy_search.FuzzySearcher` (PyPI `fuzzy-search` 1.x), as used in Republic and related projects — unless something else is clearly better.

## Setup

- **Corpus:** all lemma candidates from Dijkstra Excel + TOC + persons index (`n = 1030`).
- **Probes:** hand-picked hard cases from structure gold (reorder, OCR typo, extra titles, control exact matches).
- **Negative pairs:** 3160 random pairs of *different* lemma display names (false-positive rate).
- **Methods compared:**
  - `seq` — `difflib.SequenceMatcher` (previous labeller default)
  - `fs_lev` — FuzzySearcher `score_levenshtein_distance_ratio` on normalized strings only
  - `fs_lev_sort` — same on **token-sorted** normalized strings
  - `combo_fs` / `combo_fs_sort` — mean of char + 2-gram + lev ratios
  - `best_fs` — max of combo/lev on raw **and** token-sorted forms (+ later: token-subset boost)
  - `rf_*` — `rapidfuzz` (`ratio`, `token_sort_ratio`, `token_set_ratio`, `WRatio`)

Normalization: lower-case, strip punctuation to spaces, collapse whitespace.

## Probe results (selected)

| Pair | seq | fs_lev | fs_lev_sort | best_fs* | rf WRatio | rf token_set |
|------|-----|--------|------------|----------|-----------|--------------|
| Oldenbarnevelt, Johan van ↔ Johan van Oldenbarnevelt | 0.58 | **0.17** | **1.00** | **1.00** | 0.95 | 1.00 |
| Wicquefort ↔ Wicquefon (OCR) | 0.93 | 0.90 | 0.90 | 0.90 | 0.93 | 0.93 |
| Eden, William baron Auckland ↔ Eden, William | 0.62 | 0.44 | 0.44 | 0.44† | 0.90 | **1.00** |
| Taffin, Quitin … ↔ Taffin, Quintin | 0.60 | 0.41 | 0.41 | 0.43 | 0.87 | 0.60 |
| Exact controls (Aubéry, Gomm, Calvart) | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |

\* `best_fs` as first implemented (max combo/lev × raw/sorted).  
† Token-subset boost later raises this to **0.92** when all tokens of the shorter name appear in the longer.

### Takeaways from probes

1. **Raw Levenshtein alone is unsafe** for Dutch person names: particle/surname order tanks the score (0.17 on a true match).
2. **Token-sorting before FuzzySearcher lev/combo** fixes reorder.
3. **WRatio / token_set** look strong on “Excel has extra titles”, but see FP rates below.

## Corpus TOC: flips vs old `SequenceMatcher` @ 0.55

| Method | Newly pass (rescued) | Newly fail (regressed) |
|--------|----------------------|-------------------------|
| `seq` (baseline) | 0 | 0 |
| `fs_lev` (raw) | 0 | **67** |
| `fs_lev_sort` | 8 | 13 |
| `combo_fs` / `combo_fs_sort` / `best_fs` | **11** | **1** |
| `rf_token_sort` | 8 | 0 |
| `rf_token_set` | 10 | 0 |
| `rf_W` | 11 | 0 |

Raw FuzzySearcher levenshtein **regresses** dozens of good headers. Combo + sort **rescues** the same band of near-misses as WRatio without that damage.

## False positives (random different names)

| Threshold | rf WRatio | rf token_set | best_fs | seq |
|-----------|-----------|--------------|---------|-----|
| 0.55 | 4.53% | 1.23% | 0.82% | 0.73% |
| 0.70 | 3.10% | 0.19% | 0.06% | 0.06% |
| 0.80 | 3.04% | 0.03% | 0.03% | 0.03% |

**WRatio stays ~3% FP** even at high thresholds → too loose for identity checks.  
**best_fs** tracks SequenceMatcher’s low FP while still rescuing reorder cases.

Recall on previous `toc_ok` pairs @ 0.55: `best_fs ≈ 0.999`; rescues **11/11** then-failing TOC pairs (same count as WRatio).

### fuzzy-search 3.x bag (FP + speed, 2026-10-21)

Same 3160 random different-name pairs; v3 scores via `fuzzy_search.tokenization.string` (char + ngram + lev, raw + token-sorted, + token-subset boost) — same recipe as the 1.x bag.

| Method | @0.55 | @0.70 | @0.80 |
|--------|------:|------:|------:|
| seq (difflib) | 0.92% | 0.00% | 0.00% |
| v1 bag (`fuzzy-search==1.3.2`) | **1.01%** | 0.03% | 0.00% |
| full `name_similarity` (v1 + align) | 1.04% | 0.03% | 0.00% |
| **v3 bag** (`fuzzy-search==3.0.4`) | **2.91%** | 0.09% | 0.00% |

- v3 scores run **~+0.07** higher on average → **~3×** more FPs at the current 0.55 threshold (92 vs 32; 60 of those are v3-only).
- To match v1’s ~1% FP rate, raise v3 threshold to **≈0.61**. At that cut, Quitin/Quintin (**0.605**) fails again unless SW/DAG stays in the stack.
- Speed (1k pairs, bag only): v1 ~5.7k pairs/s vs v3 ~56k (~**10×**); full `name_similarity` still ~2k pairs/s (alignment-bound).

**Verdict:** 3.x is faster but looser at 0.55 — not a drop-in. Keep `fuzzy-search==1.3.2` for char/ngram; use **rapidfuzz** `normalized_similarity` for Lev (same classic metric as 1.x, C++ speed).

## Against known-good cases

**Definition of known-good:** pairs that already passed under the old `SequenceMatcher` TOC check (`ratio ≥ 0.55`).

| Metric | Result |
|--------|--------|
| Former `toc_ok` pairs | 1015 |
| Still pass `name_similarity` @ 0.55 | **1014 (99.90%)** |
| Regressions | **1** |
| Token-sort-identical pairs | 884 / 884 still pass |

**Former sole bag-layer regression:** `nl:1` — Excel `Taffin, Quitin heer van la Pré` vs TOC `Taffin, Quintin`. Bag-only **0.432**; with SW/DAG **0.857** (rescued). Alignment catches the Quitin/Quintin token match that bag max missed.

**Corpus header roll-up after switch** (Excel ↔ TOC/persons via `name_sim`):

| | Before (approx.) | After |
|--|------------------|-------|
| pass | 992 | **1001** |
| warn | 24 | 25 |
| fail | 14 | **4** |
| pass % | 96.3% | **97.2%** |

## Against structure gold (`structure_reviews.json`)

Gold snapshot: **26** labelled (20 issue / 2 ok / 4 skip).

### Header scores on gold lemmas

| | Count |
|--|------:|
| same TOC ok (seq & name_sim) | 13 |
| same TOC fail | 0 |
| **rescued** (seq fail → name_sim pass) | **9** |
| regressed | 1 (`nl:1`, see above) |

Rescues include title/order cases from gold: bl:92, 99, 100, 119, 250, 281, 502, 598 (and skip bl:274).  
Both gold `verdict=ok` lemmas have `header_status=pass`.

Gold header mix after name_sim: **pass 17 / warn 6 / fail 3** (fail/warn often `no_persons_index_subject` or N.N., not pure name mismatch).

### Zone repairs vs gold cues

Evaluated by re-running `load_structure_preview` (hOCR + `structure_checks`) on non-skip gold lemmas:

| Check | Result |
|-------|--------|
| Lines starting `Zoon van` / `Dochter van` / `Uit dit huwelijk` zoned `genealogy` | **23 / 23 (100%)** |
| Gold `#N: start_genealogy` (e.g. bl:23 `#40`) lands on genealogy + Zoon | **yes** |
| Notes tagging career / `genealogy_as_body` (n=10) | **8/10** clean (no remaining non-Zoon genealogy run); **2** residual (bl:240, bl:502 — period/secretary-like leftovers) |
| Gold `#N` birth / `f_death` lines with `bio_cues` set | **18 / 28 (64%)** |

**Bio-cue misses** (at evaluation time) were mostly not `geb.` / `f ` patterns: `ged.` (baptism), year-only continuations (`#2: 1601`), or `f` glued inside English titles (`tot f;`, `tot f van Gloucester`). Regex now covers `geb.` + baptism `ged.` + `birth_continued` + death-cross `f`/`t` (with `(?<!tot)` so title `tot f` does not fire).

## Decision

| Option | Verdict |
|--------|---------|
| Keep `SequenceMatcher` | Inadequate on reorder |
| FuzzySearcher **raw lev only** | Rejected (many false fails) |
| rapidfuzz `WRatio` | Rejected (high FP on unrelated names) |
| rapidfuzz `token_set` @ ~0.70 | Competitive, but new dependency / API |
| FuzzySearcher char/ngram + classic Lev, raw + token-sorted (+ subset) | Kept as bag layer (Lev → rapidfuzz) |
| Formulation Lev + SW/DAG **or** MSA alone | Rejected — use **both** |
| **Bag + Lev/SW/DAG + MSA** | **Chosen** |
| rapidfuzz `normalized_similarity` for Lev | **Chosen** (same classic `1−d/max` as FuzzySearcher 1.x; faster C++) |
| fuzzy-search 3.x / `Levenshtein.ratio` | Rejected for Lev (indel formula → ~3× FP @ 0.55) |

Implemented in `lemma_extractor/name_sim.py` as `name_similarity()` (max of bag + `name_align` SW/DAG/NW + pairwise MSA) and `name_similarity_msa()` for 3-way Excel/TOC/persons. Structure labeller header checks report `vs_toc` / `vs_persons` / `vs_msa`. Default threshold remains **0.55**.

Dependencies: `fuzzy-search==1.3.2` (char/ngram via `FuzzySearcher`); `rapidfuzz` for classic relative Levenshtein (`lev_ratio` / token `word_similarity`). Do not use fuzzy-search 3.x Lev helpers here — they wrap indel `ratio`, not `1−d/max(len)`.

## Alignment + MSA layer (and, not or)

Formulation-style token alignment lives in `lemma_extractor/name_align.py`:

| Method | Role |
|--------|------|
| `word_similarity` | Classic relative Levenshtein per token (rapidfuzz) |
| `align_sw` | Smith-Waterman local token alignment |
| `align_dag` | Layered DP with optional particle/title skips |
| `align_nw` / `msa_pairwise_similarity` | Global NW; 3-way = mean of all pairs |

`name_similarity(a, b)` takes the **max** of FuzzySearcher+rapidfuzz bag scores **and** SW/DAG (raw + sorted) **and** NW MSA — not a choice between families.

### Probe (align detail, 2026-10-21)

| Pair | bag | sw | dag | nw/msa | **total** |
|------|-----|----|-----|--------|-----------|
| Oldenbarnevelt ↔ Johan van … | 1.00 | 0.67 | 0.67 | 0.53 | **1.00** |
| Wicquefort ↔ Wicquefon | 0.90 | 0.87 | 0.87 | 0.92 | **0.92** |
| Eden … Auckland ↔ Eden, William | 0.92 | 1.00 | 1.00 | 0.50 | **1.00** |
| Quitin … ↔ Quintin | 0.43 | **0.86** | **0.86** | 0.31 | **0.86** |
| Exact Aubéry | 1.00 | 1.00 | 1.00 | 1.00 | **1.00** |

SW/DAG rescue Quitin/Quintin (former bag-only regression). Max-of-layers cannot lower bag scores → known-good pairs stay ≥ former bag.

## Related pipeline work (same session)

Gold-backed zone rules (not part of this name benchmark) live in `lemma_extractor/structure_checks.py` and run after hOCR zone correction:

- Genealogy only from `Zoon van` / `Dochter van` / `Uit dit huwelijk`, in contiguous blocks  
- Footnote gap-fill (no body↔footnote flicker)  
- `bio_cues` for `geb.` and death cross `f`/`t`

## Repro

```bash
cd lemma_extractor
uv sync
uv run python -c "
from lemma_extractor.name_sim import name_similarity as s, name_similarity_detail as d, name_similarity_msa as m
print(s('Oldenbarnevelt, Johan van', 'Johan van Oldenbarnevelt'))
print(d('Oldenbarnevelt, Johan van', 'Johan van Oldenbarnevelt'))
print(s('Wicquefort, Joachim de', 'Wicquefon, Joachim de'))
print(s('Taffin, Quitin heer van la Pré', 'Taffin, Quintin'))
print(m('Eden, William baron Auckland', 'Eden, William', 'Eden, William baron Auckland'))
"
```
