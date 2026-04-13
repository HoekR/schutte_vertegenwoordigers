"""Assemble a corpus XML file from Tesseract hOCR page files.

Each hOCR file covers one scanned page.  Pages are discovered by scanning
*hocr_dir* for ``*.hocr`` files; the 4-digit page number is extracted from
the filename suffix (e.g. ``schutte_…_0042.hocr`` → page ``0042``).

Output format mirrors the existing ``*_output_raw.xml`` files::

    <?xml version="1.0" encoding="utf-8"?>
    <root>
    <page number="0001">
    line one<br>
       line two with indent<br>
    </page>
    <page number="0002">
    …
    </root>

Lines are reconstructed as ``" " * indent + text`` using the synthetic indent
values produced by :func:`parse_hocr.parse_page` (0, 5, or 10 spaces).
Blank lines are omitted.  The result is clean UTF-8 with no double-encoding.
"""
from __future__ import annotations

import re
from pathlib import Path

from lemma_extractor.parse_hocr import parse_page

_PAGE_NUM_RE = re.compile(r"_(\d{4})\.hocr$")


def assemble(hocr_dir: Path, out_path: Path, corpus: str) -> dict[str, int]:
    """Build a corpus XML from all hOCR files found in *hocr_dir*.

    Parameters
    ----------
    hocr_dir:
        Directory containing ``*.hocr`` files for the corpus.
    out_path:
        Destination XML file (parent directories are created if needed).
    corpus:
        ``"nl"`` or ``"bl"`` — passed through to :func:`parse_hocr.parse_page`.

    Returns
    -------
    dict with keys ``pages`` (int) and ``lines`` (int).
    """
    hocr_files = sorted(hocr_dir.glob("*.hocr"))
    stats: dict[str, int] = {"pages": 0, "lines": 0}

    out_path.parent.mkdir(parents=True, exist_ok=True)

    with out_path.open("w", encoding="utf-8") as fh:
        fh.write('<?xml version="1.0" encoding="utf-8"?>\n<root>\n')

        for path in hocr_files:
            m = _PAGE_NUM_RE.search(path.name)
            if not m:
                continue
            page_nr = m.group(1)
            page_lines = parse_page(path, corpus)

            fh.write(f'<page number="{page_nr}">\n')
            for line in page_lines:
                if line["zone"] == "blank":
                    continue
                text = " " * line["indent"] + line["text"]
                fh.write(text + "<br>\n")
                stats["lines"] += 1
            fh.write("</page>\n")
            stats["pages"] += 1

        fh.write("</root>\n")

    return stats
