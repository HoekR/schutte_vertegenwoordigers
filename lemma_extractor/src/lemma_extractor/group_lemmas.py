"""
Phase 2 — Group annotated lines into per-lemma records.

Combines two inputs:
  1. The annotated line stream from ``parse_html.parse_page()`` (all HTML pages
     of a corpus read in file order).
  2. The TOC XML (``toc_nl.xml`` or ``toc_bl.xml``) which supplies authoritative
     metadata: title, period, start page number, and source file number.

Output
------
A list of lemma dicts, one per ``schutte_nr``, with this schema::

    {
        "schutte_nr":  int,         # 1-based identifier within the corpus
        "corpus":      str,         # "nl" or "bl"
        "toc_title":   str,         # "Aerssen, François van"
        "toc_chapter": str,         # "I. Frankrijk"
        "toc_page":    int,         # book page number where lemma starts
        "source_file": str,         # zero-padded file number, e.g. "0002"
        "period":      str,         # most recent period_header before the entry
        "lines": [                  # all content lines IN ORDER
            {"zone": str, "text": str, "indent": int},
            ...
        ],
        "footnotes": {              # page-bottom notes from all pages this lemma touches
            "1":  "Res. 14 maart 1587.",
            ...
        }
    }

``lines`` keeps all zones (body, genealogy, sub_note) in document order so that
the Jinja2 renderer can reproduce the original layout.  The entry header itself
(zone ``lemma_entry``) is included as the first element of ``lines``.

Notes on edge cases
-------------------
* A lemma can span multiple HTML pages.  All lines up to (but not including)
  the next ``lemma_entry`` marker are collected, regardless of page boundaries.
* Page-bottom footnotes (zone ``footnote``) are stored in ``footnotes`` keyed
  by their number string.  Where a lemma spans pages, notes from all pages are
  merged.
* ``period_header`` and ``chapter_intro`` lines at indent 0 are **not** placed
  in ``lines``; instead the most recent ``period_header`` is captured in the
  ``period`` field.
* ``page_number`` and ``blank`` lines are silently dropped.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Iterator
import xml.etree.ElementTree as ET

from .parse_html import parse_page

# ---------------------------------------------------------------------------
# TOC loading
# ---------------------------------------------------------------------------

def load_toc(toc_path: Path) -> dict[int, dict]:
    """Parse a TOC XML file and return ``{schutte_nr: metadata_dict}``.

    Metadata dict keys:
      ``title``       — display name from ``<title>`` (number stripped)
      ``full_title``  — full title string including leading number, e.g. "5. Aerssen…"
      ``chapter``     — enclosing chapter title (from parent ``level="0"`` item)
      ``page_nr``     — int book-page number from ``<page number="…">``
      ``source_file`` — zero-padded 4-digit HTML file number, e.g. ``"0002"``
    """
    tree = ET.parse(toc_path)
    root = tree.getroot()

    result: dict[int, dict] = {}
    current_chapter = ''

    for item in root.iter('item'):
        level = item.get('level', '0')
        schutte_nr_str = item.get('schutte_nr')

        # Chapter-level items (level 0) carry no schutte_nr but give us the
        # chapter title.
        if not schutte_nr_str:
            title_el = item.find('title')
            if title_el is not None and title_el.text:
                chapter_title = title_el.text.strip()
                if chapter_title:
                    current_chapter = chapter_title
            continue

        schutte_nr = int(schutte_nr_str)
        title_el = item.find('title')
        page_el = item.find('page')

        full_title = title_el.text.strip() if title_el is not None and title_el.text else ''
        # Strip the leading "N. " prefix to get a clean display name.
        clean_title = re.sub(r'^\d+\.\s+', '', full_title)

        page_nr = 0
        source_file = '0001'
        if page_el is not None:
            try:
                page_nr = int(page_el.get('number', '0'))
            except ValueError:
                page_nr = 0
            src = page_el.get('source', '1')
            try:
                source_file = f'{int(src):04d}'
            except ValueError:
                source_file = src.zfill(4)

        result[schutte_nr] = {
            'title': clean_title,
            'full_title': full_title,
            'chapter': current_chapter,
            'page_nr': page_nr,
            'source_file': source_file,
        }

    return result


# ---------------------------------------------------------------------------
# Annotated line stream
# ---------------------------------------------------------------------------

def _html_files(html_dir: Path, corpus: str) -> list[Path]:
    """Return all HTML source pages for *corpus* in file-number order."""
    if corpus == 'nl':
        pattern = 'schutte_nederlandsevertegenwoordigersinbuitenland_*.html'
    else:
        pattern = 'schutte_buitenlandsevertegenwoordigersinnederland_*.html'
    return sorted(html_dir.glob(pattern))


def _iter_lines(html_dir: Path, corpus: str) -> Iterator[dict]:
    """Yield annotated line dicts from all pages in file order.

    Each dict is the output of ``parse_html.parse_page()`` plus an extra key:
      ``source_file`` — zero-padded 4-digit file number string, e.g. ``"0023"``
    """
    for path in _html_files(html_dir, corpus):
        # Extract the 4-digit file number from the filename.
        m = re.search(r'_(\d+)\.html$', path.name)
        file_nr = m.group(1) if m else '0000'
        for ln in parse_page(path, corpus):
            ln['source_file'] = file_nr
            yield ln


# ---------------------------------------------------------------------------
# Lemma extraction regex
# ---------------------------------------------------------------------------

# Match "N.   text" or "N. text" at indent 0 (lemma_entry header).
# Captures the leading number as group 1.
_ENTRY_NUM_RE = re.compile(r'^(\d+)\.\s+')


def _entry_nr(text: str) -> int | None:
    """Return the integer leading number from a lemma_entry line, or None."""
    m = _ENTRY_NUM_RE.match(text)
    return int(m.group(1)) if m else None


# ---------------------------------------------------------------------------
# Main grouping function
# ---------------------------------------------------------------------------

def group_lemmas(html_dir: Path, toc_path: Path, corpus: str) -> list[dict]:
    """Group all HTML lines into per-lemma records.

    Parameters
    ----------
    html_dir:
        Directory containing the corpus HTML files.
    toc_path:
        Path to ``toc_nl.xml`` or ``toc_bl.xml``.
    corpus:
        ``"nl"`` or ``"bl"``.

    Returns
    -------
    List of lemma dicts sorted by ``schutte_nr``.
    """
    toc = load_toc(toc_path)

    # Build a dict of lemma records, keyed by schutte_nr, to accumulate lines.
    lemmas: dict[int, dict] = {}
    for nr, meta in toc.items():
        lemmas[nr] = {
            'schutte_nr':  nr,
            'corpus':      corpus,
            'toc_title':   meta['title'],
            'full_title':  meta['full_title'],
            'toc_chapter': meta['chapter'],
            'toc_page':    meta['page_nr'],
            'source_file': meta['source_file'],
            'period':      '',
            'lines':       [],
            'footnotes':   {},
        }

    current_nr: int | None = None   # schutte_nr of the lemma we're filling
    current_period: str = ''        # most recent period_header text
    # footnotes accumulate per-page; flushed when we hit a new page
    page_footnotes: dict[str, str] = {}
    current_file: str = ''

    for ln in _iter_lines(html_dir, corpus):
        zone = ln['zone']
        text = ln['text']
        file_nr = ln['source_file']

        # Detect page change → flush accumulated footnotes into the current lemma.
        if file_nr != current_file:
            if current_nr is not None and page_footnotes:
                lemmas[current_nr]['footnotes'].update(page_footnotes)
            page_footnotes = {}
            current_file = file_nr

        if zone in ('blank', 'page_number', 'chapter_intro'):
            continue

        if zone == 'period_header':
            current_period = text
            continue

        if zone == 'footnote':
            fn_nr = ln.get('fn_nr', '')
            fn_text = ln.get('fn_text', text)
            if fn_nr:
                page_footnotes[fn_nr] = fn_text
            continue

        if zone == 'lemma_entry':
            # Flush pending footnotes to the *previous* lemma.
            if current_nr is not None and page_footnotes:
                lemmas[current_nr]['footnotes'].update(page_footnotes)
                page_footnotes = {}

            nr = _entry_nr(text)
            if nr is not None and nr in lemmas:
                current_nr = nr
                # Record the period at entry time (only if not already set).
                if not lemmas[nr]['period']:
                    lemmas[nr]['period'] = current_period
                lemmas[nr]['lines'].append(
                    {'zone': 'entry', 'text': text, 'indent': ln['indent']}
                )
            else:
                # Unrecognised entry number — treat as body continuation.
                if current_nr is not None:
                    lemmas[current_nr]['lines'].append(
                        {'zone': 'body', 'text': text, 'indent': ln['indent']}
                    )
            continue

        # body / genealogy / sub_note → append to current lemma
        if current_nr is not None and zone in ('body', 'genealogy', 'sub_note'):
            lemmas[current_nr]['lines'].append(
                {'zone': zone, 'text': text, 'indent': ln['indent']}
            )

    # Final flush of page footnotes.
    if current_nr is not None and page_footnotes:
        lemmas[current_nr]['footnotes'].update(page_footnotes)

    return sorted(lemmas.values(), key=lambda x: x['schutte_nr'])
