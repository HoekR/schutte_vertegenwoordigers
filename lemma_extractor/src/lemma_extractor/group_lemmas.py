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

import hashlib
import json
import re
import signal
import sys
from pathlib import Path
from typing import Any, Iterator
import xml.etree.ElementTree as ET

from .parse_html import _ENTRY_RE, parse_page
from .structure_checks import apply_structure_checks
from .zone_correct import correct_html_zones
from .pdf_style import overlay_html_page

# Bump when zone_correct / structure_checks / parse_html output shape changes.
_PAGE_CACHE_VERSION = 5  # gen-block no-spin + hOCR gate + quarantine
# lemma_extractor/src/lemma_extractor/ → parents[2] = lemma_extractor/
_DEFAULT_CACHE_DIR = Path(__file__).resolve().parents[2] / ".cache" / "page_lines"
# Bail out of pathological hOCR align (SIGALRM); page goes to quarantine.json.
_DEFAULT_HOCR_TIMEOUT_S = 2.5


class _HocrTimeout(Exception):
    """Raised by SIGALRM when hOCR zone correction exceeds the budget."""


def _alarm_handler(_signum, _frame) -> None:
    raise _HocrTimeout("hOCR zone correction timed out")


def _run_with_timeout(seconds: float, fn, *args, **kwargs):
    """Run *fn* with a wall-clock alarm (Unix). Best-effort interrupt of Python code."""
    if seconds <= 0 or not hasattr(signal, "setitimer"):
        return fn(*args, **kwargs)
    prev = signal.signal(signal.SIGALRM, _alarm_handler)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        return fn(*args, **kwargs)
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0.0)
        signal.signal(signal.SIGALRM, prev)

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


def _hocr_for_html(html_path: Path) -> Path:
    """Sibling ``*_ocr/`` directory next to the HTML corpus folder."""
    return html_path.parent.parent / f"{html_path.parent.name}_ocr" / html_path.name.replace(
        ".html", ".hocr"
    )


def _file_stamp(path: Path | None) -> str:
    if path is None or not path.exists():
        return "missing"
    st = path.stat()
    return f"{st.st_mtime_ns}:{st.st_size}"


def _page_cache_key(
    html_path: Path,
    hocr_path: Path,
    *,
    use_hocr_zones: bool,
    use_pdf_style: bool,
) -> str:
    raw = "|".join(
        [
            f"v{_PAGE_CACHE_VERSION}",
            f"hocr={int(use_hocr_zones)}",
            f"pdf={int(use_pdf_style)}",
            f"html={_file_stamp(html_path)}",
            f"hocrf={_file_stamp(hocr_path) if use_hocr_zones else 'off'}",
        ]
    )
    return hashlib.sha1(raw.encode()).hexdigest()[:20]


def _cache_path(cache_dir: Path, corpus: str, file_nr: str) -> Path:
    return cache_dir / corpus / f"{file_nr}.json"


def _load_cached_lines(cache_file: Path, key: str) -> list[dict[str, Any]] | None:
    if not cache_file.exists():
        return None
    try:
        payload = json.loads(cache_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if payload.get("key") != key:
        return None
    lines = payload.get("lines")
    return lines if isinstance(lines, list) else None


def _store_cached_lines(cache_file: Path, key: str, lines: list[dict[str, Any]]) -> None:
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    # Drop per-yield fields; source_file is re-attached on load.
    slim = []
    for ln in lines:
        row = {k: v for k, v in ln.items() if k != "source_file"}
        slim.append(row)
    tmp = cache_file.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps({"key": key, "lines": slim}, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    tmp.replace(cache_file)


def _quarantine_path(cache_dir: Path) -> Path:
    return cache_dir / "quarantine.json"


def _load_quarantine(cache_dir: Path) -> dict[str, list[str]]:
    path = _quarantine_path(cache_dir)
    if not path.exists():
        return {"nl": [], "bl": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"nl": [], "bl": []}
    return {
        "nl": list(data.get("nl") or []),
        "bl": list(data.get("bl") or []),
    }


def _save_quarantine(cache_dir: Path, data: dict[str, list[str]]) -> None:
    path = _quarantine_path(cache_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _add_quarantine(cache_dir: Path, corpus: str, file_nr: str, reason: str) -> None:
    data = _load_quarantine(cache_dir)
    bucket = data.setdefault(corpus, [])
    if file_nr not in bucket:
        bucket.append(file_nr)
        bucket.sort()
        _save_quarantine(cache_dir, data)
    sys.stderr.write(
        f"\n  ! quarantine [{corpus}] file={file_nr} ({reason}) → HTML-only zones\n"
    )
    sys.stderr.flush()


def _needs_hocr_y_fix(html_lines: list[dict[str, Any]]) -> bool:
    """True when hOCR y-align is worth it: footnotes or several numbered heads."""
    n_fn = 0
    n_num = 0
    for ln in html_lines:
        if (ln.get("zone") or "") == "footnote":
            n_fn += 1
        text = ln.get("text") or ""
        if (ln.get("indent") or 0) == 0 and _ENTRY_RE.match(text):
            n_num += 1
    return n_fn > 0 or n_num > 1


def _html_only_lines(path: Path, corpus: str) -> list[dict[str, Any]]:
    return apply_structure_checks([dict(ln) for ln in parse_page(path, corpus)])


def _parse_page_lines(
    path: Path,
    corpus: str,
    file_nr: str,
    *,
    use_hocr_zones: bool,
    use_pdf_style: bool,
    hocr_timeout_s: float = _DEFAULT_HOCR_TIMEOUT_S,
    quarantined: bool = False,
    cache_dir: Path | None = None,
) -> list[dict[str, Any]]:
    """Parse one page; hOCR only when useful, with timeout → quarantine."""
    hocr = _hocr_for_html(path)
    html_lines = [dict(ln) for ln in parse_page(path, corpus)]
    use_hocr = (
        use_hocr_zones
        and not quarantined
        and hocr.exists()
        and _needs_hocr_y_fix(html_lines)
    )
    if use_hocr:
        try:
            lines = _run_with_timeout(
                hocr_timeout_s, correct_html_zones, path, hocr, corpus
            )
        except _HocrTimeout:
            if cache_dir is not None:
                _add_quarantine(cache_dir, corpus, file_nr, f"hOCR timeout>{hocr_timeout_s}s")
            lines = apply_structure_checks(html_lines)
            # On timeout during --fast, still try PDF style for this page only.
            try:
                lines = overlay_html_page(lines, corpus, file_nr)
            except FileNotFoundError:
                pass
            return lines
        except Exception as exc:  # noqa: BLE001 — page isolation
            if cache_dir is not None:
                _add_quarantine(cache_dir, corpus, file_nr, f"{type(exc).__name__}")
            lines = apply_structure_checks(html_lines)
    else:
        lines = apply_structure_checks(html_lines)

    if use_pdf_style:
        try:
            lines = overlay_html_page(lines, corpus, file_nr)
        except FileNotFoundError:
            pass
    return lines


def _iter_lines(
    html_dir: Path,
    corpus: str,
    *,
    use_hocr_zones: bool = True,
    use_pdf_style: bool = True,
    progress: bool = True,
    use_cache: bool = True,
    cache_dir: Path | None = None,
    hocr_timeout_s: float = _DEFAULT_HOCR_TIMEOUT_S,
) -> Iterator[dict]:
    """Yield annotated line dicts from all pages in file order.

    Each dict is the output of ``parse_html.parse_page()`` (optionally zone-
    corrected via hOCR bbox — HYBRID_PLAN step 2; optionally PDF italic/bold
    spans — step 3) plus:
      ``source_file`` — zero-padded 4-digit file number string, e.g. ``"0023"``

    When *use_cache* is True, page line lists are stored under
    ``lemma_extractor/.cache/page_lines/{corpus}/`` keyed by file stamps +
    flags so rebuilds skip unchanged pages.

    hOCR align runs only when the HTML page has footnotes or multiple numbered
    heads; hung pages are quarantined (HTML-only, logged under quarantine.json).
    """
    paths = _html_files(html_dir, corpus)
    total = len(paths)
    cache_root = cache_dir or _DEFAULT_CACHE_DIR
    quarantine = set(_load_quarantine(cache_root).get(corpus) or [])
    hits = misses = 0
    for i, path in enumerate(paths, start=1):
        m = re.search(r"_(\d+)\.html$", path.name)
        file_nr = m.group(1) if m else "0000"
        hocr = _hocr_for_html(path)
        key = _page_cache_key(
            path, hocr, use_hocr_zones=use_hocr_zones, use_pdf_style=use_pdf_style
        )
        cache_file = _cache_path(cache_root, corpus, file_nr)
        lines: list[dict[str, Any]] | None = None
        tag = "miss"
        if use_cache:
            lines = _load_cached_lines(cache_file, key)
            if lines is not None:
                hits += 1
                tag = "hit"
            else:
                misses += 1
        else:
            misses += 1
        in_q = file_nr in quarantine
        if progress:
            pct = 100 * i / total if total else 100
            qmark = " quarantine" if in_q else ""
            sys.stderr.write(
                f"\r  [{corpus}] page {i}/{total} ({pct:5.1f}%)  "
                f"file={file_nr}  cache={tag}{qmark}   "
            )
            sys.stderr.flush()
        if lines is None:
            lines = _parse_page_lines(
                path,
                corpus,
                file_nr,
                use_hocr_zones=use_hocr_zones,
                use_pdf_style=use_pdf_style,
                hocr_timeout_s=hocr_timeout_s,
                quarantined=in_q,
                cache_dir=cache_root,
            )
            # Refresh quarantine set after possible add
            quarantine = set(_load_quarantine(cache_root).get(corpus) or [])
            if use_cache:
                try:
                    _store_cached_lines(cache_file, key, lines)
                except OSError:
                    pass
        for ln in lines:
            row = dict(ln)
            row["source_file"] = file_nr
            yield row
    if progress and total:
        sys.stderr.write(
            f"\r  [{corpus}] pages {total}/{total} (100.0%)  "
            f"cache hit={hits} miss={misses}  "
            f"quarantine={len(quarantine)}          \n"
        )
        sys.stderr.flush()


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

def group_lemmas(
    html_dir: Path,
    toc_path: Path,
    corpus: str,
    *,
    use_hocr_zones: bool = True,
    use_pdf_style: bool = True,
    progress: bool = True,
    use_cache: bool = True,
    cache_dir: Path | None = None,
    hocr_timeout_s: float = _DEFAULT_HOCR_TIMEOUT_S,
) -> list[dict]:
    """Group all HTML lines into per-lemma records.

    Parameters
    ----------
    html_dir:
        Directory containing the corpus HTML files.
    toc_path:
        Path to ``toc_nl.xml`` or ``toc_bl.xml``.
    corpus:
        ``"nl"`` or ``"bl"``.
    use_hocr_zones:
        If True (default), correct entry/footnote zones using sibling hOCR
        bbox y-position (HYBRID_PLAN step 2).
    use_pdf_style:
        If True (default), attach italic/bold ``style_spans`` from ABBYY PDFs
        (HYBRID_PLAN step 3).
    progress:
        Print page ``i/n`` + cache hit/miss on stderr.
    use_cache:
        Cache per-page line lists under ``.cache/page_lines/``.
    cache_dir:
        Override cache root (default: ``lemma_extractor/.cache/page_lines``).
    hocr_timeout_s:
        Wall-clock budget for hOCR align; on timeout the page is quarantined
        (HTML-only + best-effort PDF style) and listed in ``quarantine.json``.
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

    for ln in _iter_lines(
        html_dir,
        corpus,
        use_hocr_zones=use_hocr_zones,
        use_pdf_style=use_pdf_style,
        progress=progress,
        use_cache=use_cache,
        cache_dir=cache_dir,
        hocr_timeout_s=hocr_timeout_s,
    ):
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
                    {
                        'zone': 'entry',
                        'text': text,
                        'indent': ln['indent'],
                        **(
                            {'style_spans': ln['style_spans']}
                            if ln.get('style_spans')
                            else {}
                        ),
                    }
                )
            else:
                # Unrecognised entry number — treat as body continuation.
                if current_nr is not None:
                    lemmas[current_nr]['lines'].append(
                        {
                            'zone': 'body',
                            'text': text,
                            'indent': ln['indent'],
                            **(
                                {'style_spans': ln['style_spans']}
                                if ln.get('style_spans')
                                else {}
                            ),
                        }
                    )
            continue

        # body / genealogy / sub_note → append to current lemma
        if current_nr is not None and zone in ('body', 'genealogy', 'sub_note'):
            row = {'zone': zone, 'text': text, 'indent': ln['indent']}
            if ln.get('style_spans'):
                row['style_spans'] = ln['style_spans']
            lemmas[current_nr]['lines'].append(row)

    # Final flush of page footnotes.
    if current_nr is not None and page_footnotes:
        lemmas[current_nr]['footnotes'].update(page_footnotes)

    # Genealogy/footnote block repairs across page boundaries (per-page
    # zone_correct cannot see Zoon… on p.N and continuation on p.N+1).
    for lemma in lemmas.values():
        if lemma["lines"]:
            lemma["lines"] = [
                ln
                for ln in apply_structure_checks(lemma["lines"])
                if ln.get("zone") != "blank"
            ]

    return sorted(lemmas.values(), key=lambda x: x['schutte_nr'])
