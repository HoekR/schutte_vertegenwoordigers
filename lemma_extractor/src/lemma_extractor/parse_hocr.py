"""
Phase 1 (hOCR variant) — Parse Tesseract hOCR output into annotated line objects.

Tesseract does not preserve the leading-space indentation convention used in the
original HTML files.  Instead, each ``ocr_line`` span carries a ``bbox`` attribute
with the pixel x-coordinate of the line's left edge.  This module converts those
x-coordinates back into a synthetic leading-space count via per-page calibration,
then delegates classification to the same ``_classify_line`` / ``parse_page``
logic used by ``parse_html``.

Indentation levels (measured as x-offset from the page's left-margin baseline):

    offset  0– 30 px  →  indent  0   (entry headers, period headers, footnotes)
    offset 30–130 px  →  indent  6   (body narrative + genealogy — visually merged)
    offset ≥ 130 px   →  indent 10   (sub-notes: secretaries, staff)

The body / genealogy distinction (indent 5 vs 6–7 in parse_html) is not
recoverable from x-coordinates alone, because both zones have essentially the same
visual indentation in the printed book.  parse_hocr therefore returns indent=6 for
all body-range lines; downstream callers should treat body and genealogy uniformly
or apply a second-pass content heuristic if needed.

The baseline x is estimated as the 5th percentile of x-values on the page,
excluding right-justified outliers (x > page_width * 0.6).

API mirrors parse_html.parse_page():

    from lemma_extractor.parse_hocr import parse_page
    lines = parse_page(hocr_path, corpus="bl")
    # → list of dicts with keys: zone, text, indent, raw, x_offset, low_conf
"""

from __future__ import annotations

import re
import statistics
from pathlib import Path

from lemma_extractor.parse_html import _classify_line

# ── constants ─────────────────────────────────────────────────────────────────

# x-offset thresholds (pixel distance from page baseline at 2× scan resolution)
_BODY_THRESHOLD = 30   # offset below this → indent 0
_SUB_THRESHOLD  = 130  # offset above this → indent 10 (sub_note)

# Synthetic indent values passed to _classify_line
_INDENT_MARGIN = 0
_INDENT_BODY   = 5   # maps to body in _classify_line (indent ≤ 5 → body)
_INDENT_SUB    = 10

# hOCR regex patterns
_LINE_SPLIT = re.compile(r"class='ocr_line'")
_LINE_X_RE  = re.compile(r'title="bbox (\d+)\s+\d+\s+(\d+)')   # x_left, x_right
_WORD_RE    = re.compile(r"class='ocrx_word'[^>]*title='[^']*x_wconf\s+(\d+)[^']*'>([^<]+)<")
_PAGE_W_RE  = re.compile(r"class='ocr_page'[^>]*title='[^>]*bbox 0 0 (\d+)")


# ── internal helpers ──────────────────────────────────────────────────────────

def _parse_lines(raw: str) -> list[tuple[int, str, list[tuple[str, int]]]]:
    """Return list of (x_left, line_text, word_confs) for every ocr_line in raw."""
    page_w_m = _PAGE_W_RE.search(raw)
    page_w = int(page_w_m.group(1)) if page_w_m else 9999

    result = []
    for chunk in _LINE_SPLIT.split(raw)[1:]:
        bm = _LINE_X_RE.search(chunk)
        if not bm:
            continue
        x = int(bm.group(1))
        # Skip lines whose left edge is in the right 40% of the page
        # (chapter/section headings that are centred or right-justified).
        if x > page_w * 0.6:
            continue
        words_and_conf: list[tuple[str, int]] = [
            (m.group(2).strip(), int(m.group(1)))
            for m in _WORD_RE.finditer(chunk)
            if m.group(2).strip()
        ]
        if not words_and_conf:
            continue
        line_text = " ".join(w for w, _ in words_and_conf)
        result.append((x, line_text, words_and_conf))
    return result


def _baseline_x(lines: list[tuple[int, str, list]]) -> int:
    """Estimate the page left-margin as the 5th-percentile x across all lines."""
    xs = [x for x, _, _ in lines]
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
        indent      int   synthetic leading-space count (0, 6, or 10)
        raw         str   the synthetic padded line passed to _classify_line
        x_offset    int   pixel offset from page baseline
        low_conf    list  [(word, confidence), …] for words below threshold
    """
    raw = path.read_text(encoding="utf-8", errors="replace")

    hocr_lines = _parse_lines(raw)
    if not hocr_lines:
        return []

    baseline = _baseline_x(hocr_lines)
    result: list[dict] = []
    prev_zone = "body"

    for x, text, wconfs in hocr_lines:
        offset = x - baseline
        indent = _x_to_indent(offset)
        padded = " " * indent + text   # mimic HTML leading-space convention

        annotated = _classify_line(padded, corpus, prev_zone)
        annotated["x_offset"] = offset
        annotated["low_conf"] = [
            (w, c) for w, c in wconfs if c < conf_threshold
        ]
        result.append(annotated)
        if annotated["zone"] not in ("blank", "page_number"):
            prev_zone = annotated["zone"]

    # Re-use parse_html's second-pass footnote→lemma_entry fix
    for i, ln in enumerate(result):
        if ln["zone"] == "footnote" and ln["indent"] == 0:
            for j in range(i + 1, len(result)):
                nxt = result[j]
                if nxt["zone"] in ("blank", "page_number"):
                    continue
                if nxt["indent"] >= 5:
                    ln["zone"] = "lemma_entry"
                break

    return result
