"""linkify_refs.py

Convert NNBW and Van der Aa citation strings found in Schutte text lines
into HTML hyperlinks pointing at resources.huygens.knaw.nl/retroboeken/.

Optionally, each link is followed by a small secondary [BP] link that passes
the retroboeken URL to the Biografisch Portaal resolver
(http://www.biografischportaal.nl/resolver?url=...) – no API call required.

Confirmed URL pattern (NNBW):
  https://resources.huygens.knaw.nl/retroboeken/nnbw/#source=VOL&page=COL
  where VOL = Roman numeral I–X as an integer, COL = column number as cited.

Van der Aa URL pattern (assumed same scheme, TODO: verify):
  https://resources.huygens.knaw.nl/retroboeken/vdaa/#source=VOL&page=PAGE
"""

import re
from urllib.parse import quote

# ---------------------------------------------------------------------------
# NNBW
# ---------------------------------------------------------------------------

_ROMAN = {
    "X": 10, "IX": 9, "VIII": 8, "VII": 7, "VI": 6,
    "V": 5,  "IV": 4, "III": 3, "II": 2,  "I": 1,
}

# Match "N.N.B.W." with optional spaces/dots, then Roman numeral, comma, column
_NNBW_RE = re.compile(
    r"(N\.?\s*N\.?\s*B\.?\s*W\.?)\s+"
    r"(X{0,1}(?:IX|IV|V?I{0,3}))"   # Roman I–X
    r",\s*(\d+)",
    re.IGNORECASE,
)

_NNBW_BASE = "https://resources.huygens.knaw.nl/retroboeken/nnbw/#source={vol}&page={col}"

# ---------------------------------------------------------------------------
# Van der Aa  (Biographisch Woordenboek der Nederlanden)
# TODO: confirm that source= is indeed the volume number for vdAA
# ---------------------------------------------------------------------------

_VDAA_RE = re.compile(
    r"((?:Aa|A\.?\s*a\.?),?\s*[Bb]iogr\.?\s*[Ww]oordenb\.?\s*(?:der\s*Nederlanden)?)"
    r"(?:,\s*(?:dl\.?\s*|d\.?\s*)?(\w+))?"   # optional volume (Roman or int)
    r"(?:,\s*(\d+))?",                          # optional page/column
    re.IGNORECASE,
)

_VDAA_BASE = "https://resources.huygens.knaw.nl/retroboeken/vdaa/#source={vol}&page={col}"

# ---------------------------------------------------------------------------
# Biografisch Portaal resolver (secondary, no API call)
# ---------------------------------------------------------------------------

_BP_RESOLVER = "http://www.biografischportaal.nl/resolver?url={encoded_url}"


def _roman_to_int(s: str) -> int | None:
    s = s.strip().upper()
    return _ROMAN.get(s)


def _bp_link(retroboeken_url: str) -> str:
    """Return a small secondary [BP] link via the resolver."""
    encoded = quote(retroboeken_url, safe="")
    resolver_url = _BP_RESOLVER.format(encoded_url=encoded)
    return f'<a class="bp-resolver" href="{resolver_url}" title="Biografisch Portaal">[BP]</a>'


def linkify_nnbw(text: str, include_bp_link: bool = False) -> str:
    """Replace NNBW citation strings with hyperlinks.

    Example input:  "zie N.N.B.W. IV, 392"
    Example output: 'zie <a href="https://...nnbw/#source=4&page=392">N.N.B.W. IV, 392</a>'

    If include_bp_link is True, a small secondary [BP] resolver link is appended.
    """
    def replace(m: re.Match) -> str:
        prefix, roman, col = m.group(1), m.group(2), m.group(3)
        vol = _roman_to_int(roman)
        if vol is None:
            return m.group(0)
        url = _NNBW_BASE.format(vol=vol, col=col)
        link = f'<a href="{url}">{m.group(0)}</a>'
        if include_bp_link:
            link += " " + _bp_link(url)
        return link

    return _NNBW_RE.sub(replace, text)


def linkify_vdaa(text: str, include_bp_link: bool = False) -> str:
    """Replace Van der Aa citation strings with hyperlinks (best-effort).

    The Van der Aa retroboeken URL scheme is assumed to match NNBW.
    TODO: verify source= equals volume number for vdAA.
    """
    def replace(m: re.Match) -> str:
        label = m.group(0)
        vol_str = m.group(2)
        col_str = m.group(3)
        if not vol_str or not col_str:
            return label  # can't build a URL without volume + page
        vol = _roman_to_int(vol_str)
        if vol is None:
            # try integer directly
            try:
                vol = int(vol_str)
            except ValueError:
                return label
        url = _VDAA_BASE.format(vol=vol, col=col_str)
        link = f'<a href="{url}">{label}</a>'
        if include_bp_link:
            link += " " + _bp_link(url)
        return link

    return _VDAA_RE.sub(replace, text)


def linkify(text: str, include_bp_link: bool = False) -> str:
    """Linkify all known reference types in a single pass."""
    text = linkify_nnbw(text, include_bp_link=include_bp_link)
    text = linkify_vdaa(text, include_bp_link=include_bp_link)
    return text


# ---------------------------------------------------------------------------
# CLI for quick testing
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    samples = [
        "Zie N.N.B.W. IV, 392 voor nadere gegevens.",
        "N.N.B.W. X, 1023",
        "vgl. N.N.B.W. I, 45 en N.N.B.W. III, 200",
        "Aa, Biogr. Woordenb. der Nederlanden, dl. III, 55.",
    ]

    flag = "--bp" in sys.argv
    for s in samples:
        print("IN: ", s)
        print("OUT:", linkify(s, include_bp_link=flag))
        print()
