"""PDF font-style overlay (HYBRID_PLAN step 3).

ABBYY PDFs carry Times-Roman / Times-Italic / Times-Bold.  HTML is still
canonical text; this module attaches italic/bold character spans by aligning
pdfplumber word boxes to HTML lines.

    from lemma_extractor.pdf_style import overlay_html_page, render_styled

    lines = overlay_html_page(html_lines, corpus="nl", html_file=7)
    html = render_styled(line["text"], line.get("style_spans") or [])
"""

from __future__ import annotations

import re
import tarfile
from collections import Counter
from difflib import SequenceMatcher
from pathlib import Path

import pdfplumber
from markupsafe import escape as html_escape

# …/schutte-bewerkingen/lemma_extractor/src/lemma_extractor/pdf_style.py → parents[3]
PROJECT_ROOT = Path(__file__).resolve().parents[3]
PDF_TAR = PROJECT_ROOT / "pdf_sourcs" / "schuttepdfs.tar.gz"
PDF_CACHE = PROJECT_ROOT / "pdf_sourcs" / "cache"

PDF_OFFSET = {"nl": 0, "bl": 0}

_CORPUS = {
    "nl": {
        "tar_member": (
            "schutte/2/originelen/pdf/"
            "schutte_nederlandsevertegenwoordigersinbuitenland_{page:04d}.pdf"
        ),
    },
    "bl": {
        "tar_member": (
            "schutte/1/originelen/pdf/"
            "schutte_buitenlandsevertegenwoordigersinnederland_{page:04d}.pdf"
        ),
    },
}

_SKIP = frozenset({"blank", "page_number"})
_NORM = re.compile(r"\s+")
_WORD_RE = re.compile(r"\S+")
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


def pdf_path(corpus: str, pdf_file: int) -> Path:
    """Return local PDF path, extracting from the tar archive on first use."""
    if corpus not in _CORPUS:
        raise ValueError(f"corpus must be one of {list(_CORPUS)}")
    PDF_CACHE.mkdir(parents=True, exist_ok=True)
    member = _CORPUS[corpus]["tar_member"].format(page=pdf_file)
    cached = PDF_CACHE / Path(member).name
    if cached.exists():
        return cached
    if not PDF_TAR.exists():
        raise FileNotFoundError(f"PDF archive not found: {PDF_TAR}")
    with tarfile.open(PDF_TAR, "r:gz") as tar:
        try:
            tar.extract(member, path=PDF_CACHE, filter="data")
        except KeyError as exc:
            raise FileNotFoundError(f"{member} not in archive") from exc
    extracted = PDF_CACHE / member
    if extracted.exists() and extracted != cached:
        extracted.rename(cached)
        # prune empty nested dirs left by tar extract
        for parent in [extracted.parent, extracted.parent.parent]:
            if parent != PDF_CACHE and parent.exists() and not any(parent.iterdir()):
                parent.rmdir()
    return cached


def html_file_to_pdf_file(corpus: str, html_file: int) -> int:
    return html_file + PDF_OFFSET.get(corpus, 0)


def _font_flags(fontname: str) -> tuple[bool, bool]:
    name = fontname or ""
    return ("Italic" in name, "Bold" in name)


def extract_styled_lines(corpus: str, html_file: int, *, y_tol: float = 2.0) -> list[dict]:
    """Parse one PDF page into lines of styled words.

    Each line::
        {
          "text": str,
          "x0": float,
          "top": float,
          "words": [{"text", "italic", "bold", "x0", "top"}, …],
          "italic_digits": [str, …],   # superscript footnote candidates
        }
    """
    path = pdf_path(corpus, html_file_to_pdf_file(corpus, html_file))
    with pdfplumber.open(path) as pdf:
        page = pdf.pages[0]
        raw_words = page.extract_words(extra_attrs=["fontname", "size"]) or []

    words: list[dict] = []
    for w in raw_words:
        italic, bold = _font_flags(w.get("fontname", ""))
        words.append(
            {
                "text": w["text"],
                "italic": italic,
                "bold": bold,
                "x0": float(w["x0"]),
                "top": float(w["top"]),
                "size": float(w.get("size") or 0),
            }
        )
    if not words:
        return []

    words.sort(key=lambda w: (w["top"], w["x0"]))
    lines: list[dict] = []
    bucket: list[dict] = []
    current_top: float | None = None

    def flush() -> None:
        if not bucket:
            return
        bucket.sort(key=lambda w: w["x0"])
        text = " ".join(w["text"] for w in bucket)
        lines.append(
            {
                "text": text,
                "x0": bucket[0]["x0"],
                "top": bucket[0]["top"],
                "words": list(bucket),
                "italic_digits": [
                    w["text"]
                    for w in bucket
                    if w["italic"] and re.fullmatch(r"\d+[a-z]?", w["text"])
                ],
                "fonts": dict(Counter(
                    ("I" if w["italic"] else "") + ("B" if w["bold"] else "") or "R"
                    for w in bucket
                )),
            }
        )

    for w in words:
        if current_top is None or abs(w["top"] - current_top) > y_tol:
            flush()
            bucket = [w]
            current_top = w["top"]
        else:
            bucket.append(w)
    flush()
    return lines


def _score(a: str, b: str) -> float:
    na, nb = _norm(a), _norm(b)
    if not na or not nb:
        return 0.0
    return SequenceMatcher(None, na, nb).ratio()


def _align_lines(
    html_lines: list[dict], pdf_lines: list[dict], min_ratio: float = 0.5
) -> list[tuple[dict, dict | None, float]]:
    kept_h = [ln for ln in html_lines if ln.get("zone") not in _SKIP and ln.get("text")]
    used: set[int] = set()
    pairs: list[tuple[dict, dict | None, float]] = []
    j0 = 0
    window = 10
    for h in kept_h:
        best_j, best_r = None, 0.0
        lo = max(0, j0 - 2)
        hi = min(len(pdf_lines), j0 + window)
        for j in range(lo, hi):
            if j in used:
                continue
            r = _score(h["text"], pdf_lines[j]["text"])
            if r > best_r:
                best_r, best_j = r, j
        if best_j is not None and best_r >= min_ratio:
            used.add(best_j)
            pairs.append((h, pdf_lines[best_j], best_r))
            j0 = best_j + 1
        else:
            pairs.append((h, None, 0.0))
    return pairs


def _html_tokens(text: str) -> list[tuple[int, int, str]]:
    """Return (start, end, token) for non-whitespace tokens in *text*."""
    return [(m.start(), m.end(), m.group()) for m in _WORD_RE.finditer(text)]


def _map_styles(html_text: str, pdf_words: list[dict]) -> list[dict]:
    """Map PDF word styles onto character spans in HTML text."""
    tokens = _html_tokens(html_text)
    if not tokens or not pdf_words:
        return []

    spans: list[dict] = []
    pi = 0
    for start, end, tok in tokens:
        # advance pdf cursor to best match near pi
        best_j, best_r = None, 0.0
        for j in range(pi, min(pi + 4, len(pdf_words))):
            r = _score(tok, pdf_words[j]["text"])
            if r > best_r:
                best_r, best_j = r, j
        if best_j is None or best_r < 0.55:
            continue
        pw = pdf_words[best_j]
        pi = best_j + 1
        if pw["italic"] or pw["bold"]:
            spans.append(
                {
                    "start": start,
                    "end": end,
                    "italic": pw["italic"],
                    "bold": pw["bold"],
                }
            )
    return _merge_spans(spans)


def _merge_spans(spans: list[dict]) -> list[dict]:
    if not spans:
        return []
    spans = sorted(spans, key=lambda s: s["start"])
    out = [dict(spans[0])]
    for s in spans[1:]:
        prev = out[-1]
        # merge if adjacent/overlapping and same flags (allow single space gap)
        if (
            s["start"] <= prev["end"] + 1
            and s["italic"] == prev["italic"]
            and s["bold"] == prev["bold"]
        ):
            prev["end"] = max(prev["end"], s["end"])
        else:
            out.append(dict(s))
    return out


def render_styled(text: str, spans: list[dict] | None) -> str:
    """Escape *text* and wrap style spans in ``<i>`` / ``<b>``."""
    if not spans:
        return str(html_escape(text))
    spans = sorted(spans, key=lambda s: s["start"])
    parts: list[str] = []
    pos = 0
    for s in spans:
        start, end = s["start"], s["end"]
        if start < pos or start >= len(text):
            continue
        end = min(end, len(text))
        if start > pos:
            parts.append(str(html_escape(text[pos:start])))
        chunk = str(html_escape(text[start:end]))
        if s.get("italic"):
            chunk = f"<i>{chunk}</i>"
        if s.get("bold"):
            chunk = f"<b>{chunk}</b>"
        parts.append(chunk)
        pos = end
    if pos < len(text):
        parts.append(str(html_escape(text[pos:])))
    return "".join(parts)


def overlay_html_page(
    html_lines: list[dict],
    corpus: str,
    html_file: int | str,
) -> list[dict]:
    """Return copies of *html_lines* with ``style_spans`` where PDF aligns.

    Also sets:
      ``italic_digits`` — PDF italic digit tokens on the matched line
      ``pdf_align`` — similarity ratio
    Lines without a PDF match are returned unchanged (copied).
    """
    file_nr = int(html_file)
    out = [dict(ln) for ln in html_lines]
    try:
        pdf_lines = extract_styled_lines(corpus, file_nr)
    except FileNotFoundError:
        return out

    # Align using copies that correspond to `out`
    pairs = _align_lines(out, pdf_lines)
    by_id = {id(h): (p, r) for h, p, r in pairs}

    for ln in out:
        hit = by_id.get(id(ln))
        if not hit:
            continue
        pdf_ln, ratio = hit
        if pdf_ln is None:
            continue
        ln["pdf_align"] = round(ratio, 3)
        ln["italic_digits"] = list(pdf_ln.get("italic_digits") or [])
        ln["style_spans"] = _map_styles(ln["text"], pdf_ln["words"])
    return out


def italic_footnote_markers(html_lines: list[dict]) -> list[str]:
    """Collect unique italic digit markers seen on overlaid lines."""
    found: list[str] = []
    seen: set[str] = set()
    for ln in html_lines:
        for d in ln.get("italic_digits") or []:
            if d not in seen:
                seen.add(d)
                found.append(d)
    return found
