"""Hybrid zone correction: HTML text + hOCR bbox (HYBRID_PLAN step 2).

Keeps HTML as canonical text; overlays entry/footnote decisions from hOCR
vertical position when the two classifiers disagree on numbered indent-0 lines.

    from lemma_extractor.zone_correct import correct_html_zones
    lines = correct_html_zones(html_path, hocr_path, corpus="nl")
"""

from __future__ import annotations

import re
from pathlib import Path

from rapidfuzz import fuzz

from lemma_extractor.parse_html import _ENTRY_RE, parse_page as html_parse
from lemma_extractor.parse_hocr import FOOTNOTE_Y_FRAC, parse_page as hocr_parse
from lemma_extractor.structure_checks import apply_structure_checks

_SKIP = frozenset({"blank", "page_number"})
_NORM = re.compile(r"\s+")
# Strip leading lemma/footnote number so OCR-split "9." + "Name…" still matches.
_LEAD_NUM = re.compile(r"^\d+[a-z]?\.\s*")
# Typical footnote openings (NL/BL Schutte notes) — do not promote these to entries.
_FOOTNOTE_CONTENT = re.compile(
    r"^\d+[a-z]?\.\s+"
    r"(?:"
    r"(?:Zijn|Haar|Hun|Hunne)\s+verbaal"
    r"|Verbaal\b"
    r"|(?:Res|Ress|Miss)\.?\s"
    r"|Zie\s+ook\b"
    r"|Getuigen\b"
    r")",
    re.IGNORECASE,
)
# Light OCR / footnote-marker folding for alignment only
_OCR_FOLD = str.maketrans(
    {
        "®": " ",
        "^": " ",
        "ê": "e",
        "é": "e",
        "è": "e",
        "ë": "e",
        "á": "a",
        "à": "a",
        "â": "a",
        "ó": "o",
        "ò": "o",
        "ô": "o",
        "ú": "u",
        "ù": "u",
        "û": "u",
        "í": "i",
        "ì": "i",
        "î": "i",
        "ç": "c",
        "ñ": "n",
    }
)


def _norm(text: str) -> str:
    t = text.translate(_OCR_FOLD)
    t = re.sub(r"&#\d+;", " ", t)
    return _NORM.sub(" ", t).strip().lower()


def _norm_body(text: str) -> str:
    return _LEAD_NUM.sub("", _norm(text)).strip()


def _tokens(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9]{3,}", _norm_body(text))}


def _score(html_text: str, ocr_text: str) -> float:
    """Similarity robust to OCR splits and diacritic noise.

    Uses rapidfuzz (C++) instead of ``difflib.SequenceMatcher``, which was the
    dominant cost in ``correct_html_zones`` and can go quadratic on messy OCR.
    """
    a, b = _norm(html_text), _norm(ocr_text)
    r_full = fuzz.ratio(a, b) / 100.0
    ab, bb = _norm_body(html_text), _norm_body(ocr_text)
    r_body = (
        fuzz.ratio(ab, bb) / 100.0 if len(ab) >= 8 and len(bb) >= 8 else 0.0
    )
    # Token Jaccard on content words (handles OCR append of next line)
    ta, tb = _tokens(html_text), _tokens(ocr_text)
    r_tok = 0.0
    if len(ta) >= 2 and len(tb) >= 2:
        r_tok = len(ta & tb) / len(ta | tb)
        # Coverage of HTML tokens in OCR (OCR often longer)
        if ta:
            r_tok = max(r_tok, len(ta & tb) / len(ta))
    return max(r_full, r_body, r_tok)


def _align(
    html_lines: list[dict], hocr_lines: list[dict], min_ratio: float = 0.55
) -> list[tuple[dict, dict | None, float]]:
    """Greedy sequential align: each HTML line → best unused nearby hOCR line."""
    kept_h = [ln for ln in html_lines if ln["zone"] not in _SKIP and ln.get("text")]
    kept_o = [ln for ln in hocr_lines if ln["zone"] not in _SKIP and ln.get("text")]
    used: set[int] = set()
    pairs: list[tuple[dict, dict | None, float]] = []
    j0 = 0
    window = 12

    for h in kept_h:
        best_j, best_r = None, 0.0
        lo = max(0, j0 - 2)
        hi = min(len(kept_o), j0 + window)
        for j in range(lo, hi):
            if j in used:
                continue
            r = _score(h["text"], kept_o[j]["text"])
            # Prefer content-bearing OCR lines over bare "9." stubs
            if len(_norm_body(kept_o[j]["text"])) < 4:
                r *= 0.4
            if r > best_r:
                best_r, best_j = r, j
        if best_j is not None and best_r >= min_ratio:
            used.add(best_j)
            pairs.append((h, kept_o[best_j], best_r))
            j0 = best_j + 1
        else:
            pairs.append((h, None, 0.0))

    # Second pass: unmatched entry/footnote lines search unused OCR globally
    unmatched = [(i, h, o, r) for i, (h, o, r) in enumerate(pairs) if o is None]
    for i, h, _o, _r in unmatched:
        if h["zone"] not in ("footnote", "lemma_entry"):
            continue
        best_j, best_r = None, 0.0
        for j, ocr in enumerate(kept_o):
            if j in used:
                continue
            r = _score(h["text"], ocr["text"])
            if len(_norm_body(ocr["text"])) < 4:
                r *= 0.4
            if r > best_r:
                best_r, best_j = r, j
        if best_j is not None and best_r >= min_ratio:
            used.add(best_j)
            pairs[i] = (h, kept_o[best_j], best_r)

    return pairs


def _followed_by_body(html_lines: list[dict], target: dict) -> bool:
    try:
        i = html_lines.index(target)
    except ValueError:
        return False
    for j in range(i + 1, len(html_lines)):
        nxt = html_lines[j]
        if nxt["zone"] in _SKIP:
            continue
        return nxt.get("indent", 0) >= 5
    return False


def correct_html_zones(
    html_path: Path,
    hocr_path: Path,
    corpus: str,
) -> list[dict]:
    """Parse HTML, then correct entry/footnote zones using aligned hOCR y.

    Returns a shallow copy of HTML line dicts. Corrected lines gain:
      zone_orig   — zone before correction
      zone_reason — why it changed (or why it was confirmed)
      y_frac      — from aligned hOCR line when available
    """
    html_lines = html_parse(html_path, corpus)
    if not hocr_path.exists():
        return apply_structure_checks([dict(ln) for ln in html_lines])

    hocr_lines = hocr_parse(hocr_path, corpus)
    # Work on copies so callers can compare
    out = [dict(ln) for ln in html_lines]
    # Align using the copy objects that correspond 1:1 to html_lines kept subset
    # Re-parse alignment against `out` by matching text+index
    pairs = _align(out, hocr_lines)

    corrections = {id(h): (o, r) for h, o, r in pairs}

    for ln in out:
        hit = corrections.get(id(ln))
        if not hit:
            continue
        ocr, ratio = hit
        if ocr is None:
            continue

        y_frac = ocr.get("y_frac")
        ln["y_frac"] = y_frac
        ln["hocr_zone"] = ocr["zone"]
        ln["align_ratio"] = ratio
        in_band = y_frac is not None and y_frac >= FOOTNOTE_Y_FRAC
        followed = _followed_by_body(out, ln)

        if ln["zone"] == "footnote":
            # Mid-page numbered line that looks like an entry → restore entry.
            # Skip typical note wording (verbaal / Res. / …) even if slightly above band.
            if (
                not in_band
                and not _FOOTNOTE_CONTENT.match(ln["text"])
                and (_ENTRY_RE.match(ln["text"]) or ocr["zone"] == "lemma_entry")
            ):
                ln["zone_orig"] = "footnote"
                ln["zone"] = "lemma_entry"
                ln["zone_reason"] = "hocr_y_promote_entry"
            elif in_band or _FOOTNOTE_CONTENT.match(ln["text"]):
                ln["zone_reason"] = "hocr_y_confirm_footnote"

        elif ln["zone"] == "lemma_entry":
            # Page-bottom "entry" that is really a note → footnote.
            # Do not demote person entries that merely start near the page end
            # (body may continue on the next page).
            if in_band and _FOOTNOTE_CONTENT.match(ln["text"]) and not followed:
                ln["zone_orig"] = "lemma_entry"
                ln["zone"] = "footnote"
                ln["zone_reason"] = "hocr_y_demote_footnote"

    # Gold-backed block repairs (genealogy from Zoon…; footnote coherence; bio cues)
    return apply_structure_checks(out)


def correct_page_pair(
    html_path: Path,
    hocr_path: Path,
    corpus: str,
) -> dict:
    """Return summary of corrections for one page (for audits)."""
    raw = html_parse(html_path, corpus)
    fixed = correct_html_zones(html_path, hocr_path, corpus)
    changes = []
    for a, b in zip(raw, fixed):
        if a["zone"] != b["zone"]:
            changes.append(
                {
                    "from": a["zone"],
                    "to": b["zone"],
                    "reason": b.get("zone_reason", ""),
                    "y_frac": b.get("y_frac"),
                    "text": a["text"][:100],
                }
            )
    return {
        "page": html_path.stem.split("_")[-1],
        "n_lines": len(fixed),
        "n_changed": len(changes),
        "changes": changes,
    }
