"""
Phase 1 (hOCR variant) — Parse Tesseract hOCR output into annotated line objects.

Tesseract does not preserve the leading-space indentation convention used in the
original HTML files.  Instead, each ``ocr_line`` span carries a ``bbox`` attribute
with the pixel coordinates of the line.  This module converts left-edge
x-coordinates back into a synthetic leading-space count via per-page calibration,
then delegates classification to the same ``_classify_line`` logic used by
``parse_html``.

Indentation levels (measured as x-offset from the page's left-margin baseline):

    offset  0– 30 px  →  indent  0   (entry headers, period headers, footnotes)
    offset 30–130 px  →  indent  6   (body narrative + genealogy — visually merged)
    offset ≥ 130 px   →  indent 10   (sub-notes: secretaries, staff)

Vertical position (y) disambiguates indent-0 numbered lines:

    y_frac ≥ FOOTNOTE_Y_FRAC  →  prefer footnote (page-bottom notes)
    y_frac <  FOOTNOTE_Y_FRAC →  allow footnote→lemma_entry promotion

The body / genealogy distinction (indent 5 vs 6–7 in parse_html) is not
recoverable from x-coordinates alone.

API mirrors parse_html.parse_page():

    from lemma_extractor.parse_hocr import parse_page
    lines = parse_page(hocr_path, corpus="bl")
    # → zone, text, indent, raw, x_offset, y0, y_frac, page_h, low_conf
"""

from __future__ import annotations

import re
from pathlib import Path

from lemma_extractor.parse_html import _classify_line

# ── constants ─────────────────────────────────────────────────────────────────

# x-offset thresholds (pixel distance from page baseline at 2× scan resolution)
_BODY_THRESHOLD = 30   # offset below this → indent 0
_SUB_THRESHOLD = 130   # offset above this → indent 10 (sub_note)

# Fraction of page height: lines at or below this band are page-bottom footnotes.
# Empirically ~0.78 separates body wrap from note blocks (HYBRID_PLAN step 2).
FOOTNOTE_Y_FRAC = 0.78

# Synthetic indent values passed to _classify_line
_INDENT_MARGIN = 0
_INDENT_BODY = 5   # maps to body in _classify_line (indent ≤ 5 → body)
_INDENT_SUB = 10

# hOCR regex patterns
_LINE_SPLIT = re.compile(r"class='ocr_line'")
_LINE_BBOX_RE = re.compile(r'title="bbox (\d+)\s+(\d+)\s+(\d+)\s+(\d+)')
_WORD_RE = re.compile(
    r"class='ocrx_word'[^>]*title='[^']*x_wconf\s+(\d+)[^']*'>([^<]+)<"
)
_PAGE_BOX_RE = re.compile(r"class='ocr_page'[^>]*title='[^>]*bbox 0 0 (\d+)\s+(\d+)")


# ── internal helpers ──────────────────────────────────────────────────────────

def _parse_lines(
    raw: str,
) -> tuple[int, int, list[tuple[int, int, int, str, list[tuple[str, int]]]]]:
    """Return (page_w, page_h, lines) with lines as (x0, y0, y1, text, word_confs)."""
    page_m = _PAGE_BOX_RE.search(raw)
    page_w = int(page_m.group(1)) if page_m else 9999
    page_h = int(page_m.group(2)) if page_m else 9999

    result: list[tuple[int, int, int, str, list[tuple[str, int]]]] = []
    for chunk in _LINE_SPLIT.split(raw)[1:]:
        bm = _LINE_BBOX_RE.search(chunk)
        if not bm:
            continue
        x0, y0, _x1, y1 = (int(bm.group(i)) for i in range(1, 5))
        # Skip lines whose left edge is in the right 40% of the page
        # (chapter/section headings that are centred or right-justified).
        if x0 > page_w * 0.6:
            continue
        words_and_conf: list[tuple[str, int]] = [
            (m.group(2).strip(), int(m.group(1)))
            for m in _WORD_RE.finditer(chunk)
            if m.group(2).strip()
        ]
        if not words_and_conf:
            continue
        line_text = " ".join(w for w, _ in words_and_conf)
        result.append((x0, y0, y1, line_text, words_and_conf))
    return page_w, page_h, result


def _baseline_x(lines: list[tuple[int, int, int, str, list]]) -> int:
    """Estimate the page left-margin as the 5th-percentile x across all lines."""
    xs = [x for x, *_ in lines]
    if not xs:
        return 0
    xs.sort()
    idx = max(0, int(len(xs) * 0.05) - 1)
    return xs[idx]


def _x_to_indent(offset: int) -> int:
    if offset < _BODY_THRESHOLD:
        return _INDENT_MARGIN
    if offset < _SUB_THRESHOLD:
        return _INDENT_BODY
    return _INDENT_SUB


def _followed_by_body(lines: list[dict], i: int) -> bool:
    for j in range(i + 1, len(lines)):
        nxt = lines[j]
        if nxt["zone"] in ("blank", "page_number"):
            continue
        return nxt["indent"] >= 5
    return False


def _resolve_entry_footnote(lines: list[dict]) -> None:
    """Disambiguate indent-0 numbered lines using y-band + lookahead.

    - Above the footnote band: promote footnote→lemma_entry when followed by body
      (same rule as parse_html), unless the line looks like a typical note.
    - In the footnote band: force footnote only for note-like wording; keep
      person entries that merely start near the page bottom.
    """
    # Imported lazily to avoid a hard cycle if zone_correct ever imports parse_hocr helpers
    import re

    note_re = re.compile(
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

    for i, ln in enumerate(lines):
        y_frac = ln.get("y_frac")
        in_band = y_frac is not None and y_frac >= FOOTNOTE_Y_FRAC
        followed = _followed_by_body(lines, i)
        note_like = bool(note_re.match(ln.get("text", "")))

        if ln["zone"] == "footnote" and ln["indent"] == 0:
            if followed and not in_band and not note_like:
                ln["zone"] = "lemma_entry"
                ln["zone_reason"] = "hocr_promote_entry"
            elif in_band or note_like:
                ln["zone_reason"] = "hocr_y_footnote"
        elif ln["zone"] == "lemma_entry" and ln["indent"] == 0 and in_band:
            if note_like and not followed:
                ln["zone"] = "footnote"
                ln["zone_reason"] = "hocr_y_demote_footnote"


# ── public API ────────────────────────────────────────────────────────────────

def parse_page(path: Path, corpus: str, conf_threshold: int = 80) -> list[dict]:
    """Parse one hOCR file and return a list of annotated line dicts.

    Parameters
    ----------
    path:
        Absolute path to the ``.hocr`` file.
    corpus:
        ``"nl"`` (binnenland) or ``"bl"`` (buitenland).
    conf_threshold:
        Words with Tesseract confidence below this value are flagged in the
        ``low_conf`` field of each line dict.

    Returns
    -------
    list of dicts with keys:

        zone        str   same zone names as parse_html
        text        str   stripped OCR text
        indent      int   synthetic leading-space count (0, 5, or 10)
        raw         str   the synthetic padded line passed to _classify_line
        x_offset    int   pixel offset from page baseline
        y0          int   top of line bbox
        y_frac      float y0 / page_h
        page_h      int   page height in pixels
        low_conf    list  [(word, confidence), …] for words below threshold
        zone_reason str   optional; set when y-band overrides zone
    """
    raw = path.read_text(encoding="utf-8", errors="replace")

    _page_w, page_h, hocr_lines = _parse_lines(raw)
    if not hocr_lines:
        return []

    baseline = _baseline_x(hocr_lines)
    result: list[dict] = []
    prev_zone = "body"

    for x0, y0, _y1, text, wconfs in hocr_lines:
        offset = x0 - baseline
        indent = _x_to_indent(offset)
        padded = " " * indent + text  # mimic HTML leading-space convention

        annotated = _classify_line(padded, corpus, prev_zone)
        annotated["x_offset"] = offset
        annotated["y0"] = y0
        annotated["y_frac"] = y0 / page_h if page_h else 0.0
        annotated["page_h"] = page_h
        annotated["low_conf"] = [
            (w, c) for w, c in wconfs if c < conf_threshold
        ]
        result.append(annotated)
        if annotated["zone"] not in ("blank", "page_number"):
            prev_zone = annotated["zone"]

    _resolve_entry_footnote(result)
    return result
