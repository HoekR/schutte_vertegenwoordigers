"""
linkify_refs.py — Replace NNBW and Van der Aa citation strings with HTML
hyperlinks pointing directly to the retroboeken viewer.

No API or database access is required; all links are constructed mechanically
from the citation itself.

Confirmed URL patterns
-----------------------
NNBW (10 volumes):
  https://resources.huygens.knaw.nl/retroboeken/nnbw/#source=<vol>&page=<col>
  where <vol> = integer 1–10 (Roman I…X) and <col> = column number.

Van der Aa (21 volumes):
  https://resources.huygens.knaw.nl/retroboeken/vdaa/#source=<vol>&page=<page>
  where <vol> = integer 1–21 (Roman I…XXI).

  Note: citation form "Van der Aa XII, 1, 363" encodes (volume, part, page).
  Only volume and the last page number are used for the URL; the part number
  is ignored because the retroboeken source index already separates volumes.

Usage
-----
    from lemma_extractor.linkify_refs import linkify_nnbw, linkify_vdaa, linkify_all

    html_text = linkify_all(plain_text)
"""

import re

# ---------------------------------------------------------------------------
# Roman-numeral lookup tables
# ---------------------------------------------------------------------------

# NNBW: volumes I–X
_NNBW_ROMAN: dict[str, int] = {
    "I": 1, "II": 2, "III": 3, "IV": 4, "V": 5,
    "VI": 6, "VII": 7, "VIII": 8, "IX": 9, "X": 10,
}

# Van der Aa: volumes I–XXI
_VDAA_ROMAN: dict[str, int] = {
    "I": 1, "II": 2, "III": 3, "IV": 4, "V": 5,
    "VI": 6, "VII": 7, "VIII": 8, "IX": 9, "X": 10,
    "XI": 11, "XII": 12, "XIII": 13, "XIV": 14, "XV": 15,
    "XVI": 16, "XVII": 17, "XVIII": 18, "XIX": 19, "XX": 20,
    "XXI": 21,
}

# ---------------------------------------------------------------------------
# URL templates
# ---------------------------------------------------------------------------

_NNBW_BASE = (
    "https://resources.huygens.knaw.nl/retroboeken/nnbw/"
    "#source={vol}&amp;page={col}"
)
_VDAA_BASE = (
    "https://resources.huygens.knaw.nl/retroboeken/vdaa/"
    "#source={vol}&amp;page={page}"
)

# ---------------------------------------------------------------------------
# Regular expressions
# ---------------------------------------------------------------------------

# Roman numerals for NNBW (I–X), longest match first (prevents I matching IX).
# Allow common OCR confusions: ï/Ï for I, l for I, v for V, x for X.
_ROMAN_CHARS = r"[IVXivxïÏlT]+"
_NNBW_NUMERALS = _ROMAN_CHARS

# Roman numerals for Van der Aa (I–XXI), longest match first.
_VDAA_NUMERALS = _ROMAN_CHARS

# N.N.B.W. [roman], [column]
# Allows optional spaces between the abbreviated letters to accommodate OCR.
_NNBW_RE = re.compile(
    r"N\.?\s*N\.?\s*B\.?\s*W\.?\s+"
    r"(?P<roman>" + _NNBW_NUMERALS + r")"
    r",\s*"
    r"(?P<col>\d+)"
)

# Van der Aa [roman], [optional: part,] [page]
# Handles both "Van der Aa I, 24" and "Van der Aa XII, 1, 363".
_VDAA_RE = re.compile(
    r"Van der Aa\s+"
    r"(?P<roman>" + _VDAA_NUMERALS + r")"
    r",\s*"
    r"(?:\d+,\s*)?"          # optional part number followed by comma
    r"(?P<page>\d+)"
)

# ---------------------------------------------------------------------------
# OCR normalisation helpers
# ---------------------------------------------------------------------------

# Common single-character OCR confusions inside Roman numerals:
#   ï / Ï  →  I   (i-diaeresis misread)
#   l      →  I   (lowercase L misread as I)
#   T      →  I   (capital T misread for I in serifed fonts)
#   v      →  V   (lowercase v)
#   x      →  X   (lowercase x)
_OCR_ROMAN_TR = str.maketrans("ïÏilTvx", "IIIIIVX")  # ï/Ï/i/l/T→I, v→V, x→X


def _normalize_roman(s: str) -> str:
    """Fix common OCR artefacts in a Roman-numeral string."""
    return s.translate(_OCR_ROMAN_TR)


# ---------------------------------------------------------------------------
# Replacement helpers
# ---------------------------------------------------------------------------


def _nnbw_replace(m: re.Match) -> str:
    roman = _normalize_roman(m.group("roman"))
    vol = _NNBW_ROMAN.get(roman)
    if vol is None:
        return m.group(0)  # unrecognised – leave as-is
    url = _NNBW_BASE.format(vol=vol, col=m.group("col"))
    return f'<a href="{url}">{m.group(0)}</a>'


def _vdaa_replace(m: re.Match) -> str:
    roman = _normalize_roman(m.group("roman"))
    vol = _VDAA_ROMAN.get(roman)
    if vol is None:
        return m.group(0)
    url = _VDAA_BASE.format(vol=vol, page=m.group("page"))
    return f'<a href="{url}">{m.group(0)}</a>'


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def linkify_nnbw(text: str) -> str:
    """Wrap NNBW citation strings in <a> tags."""
    return _NNBW_RE.sub(_nnbw_replace, text)


def linkify_vdaa(text: str) -> str:
    """Wrap Van der Aa citation strings in <a> tags."""
    return _VDAA_RE.sub(_vdaa_replace, text)


def linkify_all(text: str) -> str:
    """Wrap all supported citation strings in <a> tags."""
    text = linkify_nnbw(text)
    text = linkify_vdaa(text)
    return text
