"""
Phase 4 — Build cross-reference data structures.

Takes the output of ``group_lemmas.group_lemmas()`` and
``parse_index.parse_persons()`` / ``parse_index.parse_geo()`` for both
corpora and constructs:

1. **page → lemma map** — ``{corpus: {page_nr: schutte_nr}}``
   Derived from TOC data: each lemma's ``toc_page`` is the first book-page
   on which it appears.  Because multiple lemmas can share a page, the map
   returns a *list* of schutte_nrs per page.

2. **person cross-references** — for each named person in the index, the
   pages they appear on are resolved to lemma identifiers.

3. **geo cross-references** — same for places.

4. **lemma enrichment** — each lemma dict gains extra keys:
   ``"mentioned_in"`` : list of {corpus, schutte_nr} dicts for other
   lemmas that mention this person.

Output
------
``build_refs(nl_lemmas, bl_lemmas, nl_persons, bl_persons, nl_geo, bl_geo)``
→ (enriched_nl_lemmas, enriched_bl_lemmas, persons_index, geo_index)

Where:

``persons_index`` is a list of person dicts extended with:
    ``"appears_in"`` : list of {"corpus": str, "schutte_nr": int}

``geo_index`` is a list of place dicts extended with:
    ``"appears_in"`` : list of {"corpus": str, "schutte_nr": int}
"""

from __future__ import annotations

from collections import defaultdict


# ---------------------------------------------------------------------------
# Build page → [schutte_nr] maps
# ---------------------------------------------------------------------------

def _build_page_map(lemmas: list[dict]) -> dict[int, list[int]]:
    """Return ``{page_nr: [schutte_nr, ...]}`` for a single corpus."""
    page_map: dict[int, list[int]] = defaultdict(list)
    for lemma in lemmas:
        pg = lemma.get('toc_page', 0)
        if pg:
            page_map[pg].append(lemma['schutte_nr'])
    return dict(page_map)


# ---------------------------------------------------------------------------
# Resolve pages to lemma ids
# ---------------------------------------------------------------------------

def _pages_to_lemma_refs(
    pages: list[int],
    page_map: dict[int, list[int]],
    corpus: str,
) -> list[dict]:
    """Convert a list of book-page numbers to lemma references.

    A reference is ``{"corpus": str, "schutte_nr": int}``.
    Pages that don't map to any lemma (introductory pages, appendices, etc.)
    are silently dropped.
    """
    refs: list[dict] = []
    seen: set[tuple] = set()
    for pg in pages:
        for nr in page_map.get(pg, []):
            key = (corpus, nr)
            if key not in seen:
                seen.add(key)
                refs.append({'corpus': corpus, 'schutte_nr': nr})
    return refs


# ---------------------------------------------------------------------------
# Main function
# ---------------------------------------------------------------------------

def build_refs(
    nl_lemmas: list[dict],
    bl_lemmas: list[dict],
    nl_persons: list[dict],
    bl_persons: list[dict],
    nl_geo: list[dict],
    bl_geo: list[dict],
) -> tuple[list[dict], list[dict], list[dict], list[dict]]:
    """Build cross-references and enrich lemma, person, and geo records.

    Parameters
    ----------
    nl_lemmas, bl_lemmas:
        Output of ``group_lemmas.group_lemmas()`` for each corpus.
    nl_persons, bl_persons:
        Output of ``parse_index.parse_persons()`` for each corpus.
    nl_geo, bl_geo:
        Output of ``parse_index.parse_geo()`` for each corpus.

    Returns
    -------
    (enriched_nl_lemmas, enriched_bl_lemmas, persons_index, geo_index)
    """
    nl_page_map = _build_page_map(nl_lemmas)
    bl_page_map = _build_page_map(bl_lemmas)

    # -----------------------------------------------------------------------
    # Person cross-references
    # -----------------------------------------------------------------------
    persons_index: list[dict] = []

    for person in nl_persons + bl_persons:
        corpus = person['corpus']
        page_map = nl_page_map if corpus == 'nl' else bl_page_map
        appears_in = _pages_to_lemma_refs(person['pages'], page_map, corpus)
        enriched = dict(person)
        enriched['appears_in'] = appears_in
        persons_index.append(enriched)

    # -----------------------------------------------------------------------
    # Geo cross-references
    # -----------------------------------------------------------------------
    geo_index: list[dict] = []

    for place in nl_geo + bl_geo:
        corpus = place['corpus']
        page_map = nl_page_map if corpus == 'nl' else bl_page_map
        appears_in = _pages_to_lemma_refs(place['pages'], page_map, corpus)
        enriched = dict(place)
        enriched['appears_in'] = appears_in
        geo_index.append(enriched)

    # -----------------------------------------------------------------------
    # Enrich lemmas with "mentioned_in" (other lemmas that reference this person)
    # -----------------------------------------------------------------------
    # Build a lookup: schutte_nr → lemma record for fast access.
    nl_lookup = {l['schutte_nr']: l for l in nl_lemmas}
    bl_lookup = {l['schutte_nr']: l for l in bl_lemmas}

    # Initialise mentioned_in lists on every lemma.
    for l in nl_lemmas:
        l['mentioned_in'] = []
    for l in bl_lemmas:
        l['mentioned_in'] = []

    # For each person whose schutte_nr is known, their "appears_in" pages tell
    # us which *other* lemmas reference this person by name.
    for person in persons_index:
        subject_nr = person.get('schutte_nr')
        if subject_nr is None:
            continue
        subject_corpus = person['corpus']
        subject_lookup = nl_lookup if subject_corpus == 'nl' else bl_lookup
        subject_lemma = subject_lookup.get(subject_nr)
        if subject_lemma is None:
            continue

        for ref in person['appears_in']:
            ref_corpus = ref['corpus']
            ref_nr = ref['schutte_nr']
            # Skip self-reference.
            if ref_corpus == subject_corpus and ref_nr == subject_nr:
                continue
            subject_lemma['mentioned_in'].append(ref)

    return nl_lemmas, bl_lemmas, persons_index, geo_index
