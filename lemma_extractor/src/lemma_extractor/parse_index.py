"""
Phase 3 — Parse the person and geographic indexes.

Four source files are used:
  personen_index_nederland.xml   — NL person index (CR-separated, latin-1)
  personenindex_buitenland.xml   — BL person index (LF-separated, latin-1)
  geoindex_nederland.xml         — NL geographic index (LF, UTF-8)
  geoindex_buitenland.xml        — BL geographic index (LF, UTF-8)

Person index line format
------------------------
Each line is one of:

  1. Entry with schutte_nr in parentheses:
       ``Abbema, Balthasar Elias (165) 199``
       → the person is the lemma subject of schutte_nr=165 and is referenced
         on page 199.

  2. Entry without schutte_nr:
       ``Aalst, Leonardus Henricus van 396, 414``
       → a secondary mention on the given pages.

  3. See-also lines:
       ``Aelstius, zie Van Aalst``
       → stored as cross-reference, not as page pointer.

  4. Lines with page ranges like ``622/623``:
       treated as two separate pages 622 and 623.

Page numbers are space- or comma-separated integers after the name field.

Geographic index line format
-----------------------------
  ``Abbeville 62 ``
  → placename followed by space-separated or comma-separated pages.

The returned dicts use ``corpus`` = ``"nl"`` or ``"bl"`` to distinguish which
work the pages refer to.

Output
------
``parse_persons(path, corpus)`` → list of person dicts::

    {
        "name":       str,          # "Abbema, Balthasar Elias"
        "schutte_nr": int | None,   # 165, or None if not a lemma subject
        "corpus":     str,          # "nl" or "bl"
        "pages":      list[int],    # book page numbers where name appears
        "see_also":   str | None,   # "Van Aalst" for see-also lines
    }

``parse_geo(path, corpus)`` → list of place dicts::

    {
        "place":   str,         # "Abbeville"
        "corpus":  str,         # "nl" or "bl"
        "pages":   list[int],   # book page numbers
    }
"""

from __future__ import annotations

import re
from pathlib import Path

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SCHUTTE_NR_RE = re.compile(r'\((\d+)\)')
_PAGE_NUMS_RE = re.compile(r'\d+')
_PAGE_RANGE_RE = re.compile(r'(\d+)/(\d+)')   # "622/623" → 622, 623


def _parse_pages(page_str: str) -> list[int]:
    """Extract all page numbers from a raw page string.

    Handles:
      - comma-separated: ``199, 200, 201``
      - slash ranges: ``622/623`` → [622, 623]
      - bare numbers: ``199``
    """
    # Expand slash ranges first.
    expanded = _PAGE_RANGE_RE.sub(lambda m: m.group(1) + ' ' + m.group(2), page_str)
    return [int(n) for n in _PAGE_NUMS_RE.findall(expanded)]


def _read_lines(path: Path) -> list[str]:
    """Read a file as text, handling latin-1 or utf-8, normalise line endings."""
    raw = path.read_bytes()
    try:
        text = raw.decode('utf-8')
    except UnicodeDecodeError:
        text = raw.decode('latin-1')
    # Normalise CR-only, CR+LF, and plain LF to '\n'.
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    return [ln.strip() for ln in text.split('\n')]


# ---------------------------------------------------------------------------
# Person index parser
# ---------------------------------------------------------------------------

# Pattern: "Name (schutte_nr) pages"
# The schutte_nr is in parentheses immediately after the name.
_ENTRY_WITH_NR = re.compile(
    r'^(.+?)\s+\((\d+)\)\s+(.+)$'
)

# Pattern: "Name pages"  — name ends where the digit sequence starts.
# We look for the last run of non-digit content before a page number list.
_ENTRY_NO_NR = re.compile(
    r'^([A-Za-zÀ-öø-ÿ\.\,\s\(\)\*\'\-\/]+?)\s+(\d[\d\s,\/]*)$'
)

# See-also line.
_SEE_ALSO_RE = re.compile(r'^(.+?),?\s+zie(?:\s+ook)?\s+(.+)$', re.IGNORECASE)

# Skip-line patterns: section letters ("A"), XML header, header lines.
_SKIP_RE = re.compile(r'^(<\?xml|INDEX|Alleen|waar zij|\s*[A-Z]\s*$)')


def parse_persons(path: Path, corpus: str) -> list[dict]:
    """Parse a person index file and return a list of person dicts.

    Parameters
    ----------
    path:
        Path to ``personen_index_nederland.xml`` or ``personenindex_buitenland.xml``.
    corpus:
        ``"nl"`` or ``"bl"``.
    """
    lines = _read_lines(path)
    result: list[dict] = []

    for raw in lines:
        ln = raw.strip()
        if not ln:
            continue
        if _SKIP_RE.match(ln):
            continue

        # See-also lines.
        m_see = _SEE_ALSO_RE.match(ln)
        if m_see and not _PAGE_NUMS_RE.search(m_see.group(2)):
            result.append({
                'name': m_see.group(1).strip(),
                'schutte_nr': None,
                'corpus': corpus,
                'pages': [],
                'see_also': m_see.group(2).strip(),
            })
            continue

        # Entry with schutte_nr.
        m = _ENTRY_WITH_NR.match(ln)
        if m:
            result.append({
                'name': m.group(1).strip(),
                'schutte_nr': int(m.group(2)),
                'corpus': corpus,
                'pages': _parse_pages(m.group(3)),
                'see_also': None,
            })
            continue

        # Entry without schutte_nr.
        m2 = _ENTRY_NO_NR.match(ln)
        if m2:
            result.append({
                'name': m2.group(1).strip().rstrip(','),
                'schutte_nr': None,
                'corpus': corpus,
                'pages': _parse_pages(m2.group(2)),
                'see_also': None,
            })
            continue

        # Anything else: store as a bare name with no pages (might be a
        # continuation or an unusual line).
        if re.search(r'[A-Za-z]', ln):
            result.append({
                'name': ln,
                'schutte_nr': None,
                'corpus': corpus,
                'pages': [],
                'see_also': None,
            })

    return result


# ---------------------------------------------------------------------------
# Geographic index parser
# ---------------------------------------------------------------------------

# Place lines: "Placename digits…"
# Some entries have parenthetical variants: "Aken (Aachen) 257"
_GEO_LINE_RE = re.compile(
    r'^([A-Za-zÀ-öø-ÿ\s\'\-\(\)\.\/,]+?)\s+(\d[\d\s,\/]*)$'
)

# See-also geo lines.
_GEO_SEE_RE = re.compile(r'^(.+?),?\s+zie\s+(.+)$', re.IGNORECASE)


def parse_geo(path: Path, corpus: str) -> list[dict]:
    """Parse a geographic index file and return a list of place dicts.

    Parameters
    ----------
    path:
        Path to ``geoindex_nederland.xml`` or ``geoindex_buitenland.xml``.
    corpus:
        ``"nl"`` or ``"bl"``.
    """
    lines = _read_lines(path)
    result: list[dict] = []

    for raw in lines:
        ln = raw.strip()
        if not ln:
            continue
        if _SKIP_RE.match(ln):
            continue
        # Single letter section dividers.
        if re.match(r'^[A-Z]$', ln):
            continue

        # See-also.
        m_see = _GEO_SEE_RE.match(ln)
        if m_see and not _PAGE_NUMS_RE.search(m_see.group(2)):
            result.append({
                'place': m_see.group(1).strip(),
                'corpus': corpus,
                'pages': [],
                'see_also': m_see.group(2).strip(),
            })
            continue

        m = _GEO_LINE_RE.match(ln)
        if m:
            result.append({
                'place': m.group(1).strip().rstrip(','),
                'corpus': corpus,
                'pages': _parse_pages(m.group(2)),
                'see_also': None,
            })

    return result
