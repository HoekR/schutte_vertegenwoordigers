"""
Phase 1 — Parse individual HTML source pages into annotated line objects.

Each HTML page is a sequence of lines separated by ``<br>`` tags.  The
indentation (number of leading spaces) encodes the structural zone of each
line, as established by survey_structure.py:

    indent  0  period_header  Starts with a 4-digit year, e.g. "1598-1613 agent"
    indent  0  footnote       Numbered note at page bottom.
                              Binnenland format: "11.   text"  (number + dot + spaces)
                              Buitenland format: "11 text"     (number + space, no dot)
    indent  0  lemma_entry    Entry header, e.g. "5.   Mr. François van Aerssen…"
    indent  0  chapter_intro  Chapter heading or free intro paragraph — skipped
    indent  0  page_number    Bare page number, possibly right-justified — skipped
    indent  5  body           Main career narrative
    indent 6-7 genealogy      Family data and bibliography
    indent 9-11 sub_note      Secretaries, staff and other attached persons
    other      continuation   Wrap-around continuation of the preceding zone

Each output line object is a dict:
    {
        "zone":   str,    # one of the zone names above
        "text":   str,    # stripped line content (unicode, latin-1 decoded)
        "indent": int,    # original leading-space count
        "raw":    str,    # original line before stripping (useful for debugging)
    }

Notes:
    - Files are decoded as latin-1 (the actual on-disk encoding of both corpora).
    - The <br> tag is the only structural separator; no other HTML tags are used.
    - Page number lines (bare digits with optional whitespace) are returned with
      zone="page_number" so callers can use the value but easily filter them out.
    - Chapter intro lines (indent 0, none of the above patterns) are returned with
      zone="chapter_intro" — callers decide whether to keep or skip them.
"""

from __future__ import annotations

import re
from pathlib import Path

# ---------------------------------------------------------------------------
# Zone classification rules
# ---------------------------------------------------------------------------

# Period/role header: starts with a 4-digit year, e.g. "1598-1613 agent"
_PERIOD_RE = re.compile(r'^\d{4}')

# Lemma entry header: "N.   Firstname Lastname …" — number, dot, 1+ spaces,
# then an uppercase letter (the first letter of the name).
# NL uses 3–6 spaces; BL uses only 1 space.
_ENTRY_RE = re.compile(r'^\d+\.\s{1,8}[A-Z(]')

# Page-bottom footnote — binnenland style: "11.   text"
_FOOTNOTE_NL_RE = re.compile(r'^(\d+[a-z]?)\.\s{2,}(.+)')

# Page-bottom footnote — buitenland style: "11 text" (no dot after number).
# Constrain to avoid matching normal sentences that start with a digit.
# The number must be followed by a single space then a non-digit.
_FOOTNOTE_BL_RE = re.compile(r'^(\d+[a-z]?)\s([A-Z\w].+)')

# Bare page number: only digits (and whitespace), possibly right-justified.
_PAGE_NUM_RE = re.compile(r'^\s*\d+\s*$')

# Inline footnote markers: a digit sequence directly attached to a word character,
# not part of a date (heuristic: preceded by a letter or closing parenthesis).
# Examples:  "vastgesteld1"  "15933'4"  "rapport uit12"
# Captures: (word_end)(marker)(optional-punctuation)
_INLINE_FN_RE = re.compile(r'([A-Za-z\)])((\d+[a-z]?)(?=[^0-9]|$))')


def _classify_indent_0(text: str, corpus: str) -> tuple[str, dict]:
    """Classify a line with zero leading spaces.  Returns (zone, extras).

    extras may contain footnote-specific fields:
        {"fn_nr": "11", "fn_text": "Res. ..."}
    """
    stripped = text.strip()

    if not stripped:
        return 'blank', {}

    # Bare page number (skip)
    if _PAGE_NUM_RE.match(stripped):
        return 'page_number', {}

    # Footnote — try binnenland format first (more specific: requires dot)
    m = _FOOTNOTE_NL_RE.match(stripped)
    if m:
        return 'footnote', {'fn_nr': m.group(1), 'fn_text': m.group(2).strip()}

        # Period / role header — check BEFORE buitenland footnote to avoid matching
    # lines like "1637 secretaris van ambassade" as footnote nr 1637.
    if _PERIOD_RE.match(stripped):
        return 'period_header', {}

    # Footnote — buitenland format (number + space, no dot). Only accept for
    # buitenland corpus to avoid false matches in binnenland.
    # Footnote numbers are typically 1-3 digits (not 4-digit years, handled above).
    if corpus == 'bl':
        m = _FOOTNOTE_BL_RE.match(stripped)
        if m:
            return 'footnote', {'fn_nr': m.group(1), 'fn_text': m.group(2).strip()}

    # Lemma entry header
    if _ENTRY_RE.match(stripped):
        return 'lemma_entry', {}

    # Anything else at indent 0 is chapter intro material
    return 'chapter_intro', {}


def _classify_line(line: str, corpus: str, prev_zone: str) -> dict:
    """Return an annotated line dict for a single ``<br>``-separated line."""
    raw = line
    s = line.lstrip()
    indent = len(line) - len(s)
    text = s.rstrip()

    if not text:
        return {'zone': 'blank', 'text': '', 'indent': indent, 'raw': raw}

    if indent == 0:
        zone, extras = _classify_indent_0(text, corpus)
    elif indent <= 2:
        # Very slight indent — typically a continuation of a lemma entry header
        # that wraps partially (rare; treat as body).
        zone, extras = 'body', {}
    elif indent <= 4:
        # Indent 3-4 — seen in buitenland for some entry continuations
        zone, extras = 'body', {}
    elif indent <= 8:
        # Indent 5-8: body (5) or genealogy (6-7) or edge cases (8)
        zone, extras = ('body' if indent <= 5 else 'genealogy'), {}
    elif indent <= 12:
        # Indent 9-12: sub-notes (secretaries, staff)
        zone, extras = 'sub_note', {}
    else:
        # Very large indent (e.g. 82) — right-justified page number inside page
        if _PAGE_NUM_RE.match(text):
            zone, extras = 'page_number', {}
        else:
            # Fall back to continuation of previous zone
            zone, extras = prev_zone or 'body', {}

    result = {'zone': zone, 'text': text, 'indent': indent, 'raw': raw}
    result.update(extras)
    return result


def extract_inline_footnotes(text: str) -> list[str]:
    """Return list of inline footnote marker strings found in *text*.

    Only markers that are attached directly to a word character are returned.
    Date-like sequences (four consecutive digits) are excluded.
    """
    markers = []
    for m in _INLINE_FN_RE.finditer(text):
        marker = m.group(2)
        # Exclude if the surrounding context looks like a year (4-digit run)
        start = m.start(2)
        nearby = text[max(0, start - 1): start + len(marker) + 1]
        if re.fullmatch(r'\d{4,}', nearby.replace("'", '')):
            continue
        markers.append(marker)
    return markers


def parse_page(path: Path, corpus: str) -> list[dict]:
    """Parse one HTML source page and return a list of annotated line dicts.

    Parameters
    ----------
    path:
        Absolute path to the ``.html`` file.
    corpus:
        ``"nl"`` (binnenland) or ``"bl"`` (buitenland).  Used to select the
        correct footnote pattern.

    Returns
    -------
    list of annotated line dicts (see module docstring for schema).
    """
    raw_bytes = path.read_bytes()
    # Files use either UTF-8 or latin-1; try UTF-8 first.
    try:
        content = raw_bytes.decode('utf-8')
    except UnicodeDecodeError:
        content = raw_bytes.decode('latin-1')

    lines = content.split('<br>')
    result: list[dict] = []
    prev_zone = 'body'

    for raw_line in lines:
        annotated = _classify_line(raw_line, corpus, prev_zone)
        result.append(annotated)
        if annotated['zone'] not in ('blank', 'page_number'):
            prev_zone = annotated['zone']

    # Second pass: the NL footnote regex (`N.   text`) also matches lemma entry
    # headers in both corpora because they share the same punctuation format.
    # Resolve via lookahead: if the first non-blank, non-page_number line after
    # a `footnote` at indent 0 is at indent ≥ 5 (body zone), re-classify as
    # `lemma_entry`.
    for i, ln in enumerate(result):
        if ln['zone'] == 'footnote' and ln['indent'] == 0:
            for j in range(i + 1, len(result)):
                nxt = result[j]
                if nxt['zone'] in ('blank', 'page_number'):
                    continue
                if nxt['indent'] >= 5:
                    ln['zone'] = 'lemma_entry'
                break

    return result
