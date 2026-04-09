"""Extract individual lemma XML files from a tagged corpus file.

A tagged corpus file is the output of tag_xml.tag_corpus().  Each lemma is
delimited by two consecutive ``<start schuttenr="N">`` elements.  The text of
a lemma includes everything from (and including) its own ``<start>`` opening
tag up to (but not including) the next ``<start>`` opening tag, or the end of
the ``</root>`` element.

Output per lemma
----------------
``{out_dir}/{prefix}_{schuttenr:04d}.xml``

Each file is a well-formed XML fragment:

    <?xml version="1.0" encoding="utf-8"?>
    <lemma schuttenr="N" name="..." givenname="..."
           beginjaar="..." eindjaar="..." functie="..."
           category="..." corpus="nl|bl">
      <line>first line …</line>
      <line>continuation …</line>
      …
    </lemma>

Lines are split on ``<br>`` boundaries and stripped of leading/trailing space.
Empty lines (``<br><br>`` runs) are dropped.
"""
from __future__ import annotations

import re
import xml.sax.saxutils as sax
from pathlib import Path
from typing import Any


# Regex that matches an opening <start> tag and captures schuttenr + inner text
_START_RE = re.compile(
    r'<start\s+schuttenr="(\d+)">(.*?)</start>',
    re.DOTALL,
)

# Matches a closing </root> or </page> tag we want to stop before
_END_RE = re.compile(r"</root\s*>", re.IGNORECASE)


def _split_at_starts(content: str) -> list[tuple[int, str]]:
    """Return [(schuttenr, raw_text_from_start_to_next_start), …] sorted by schuttenr."""
    # Find positions of all <start …> opening tags
    positions: list[tuple[int, int, str]] = []  # (char_offset, schuttenr, inner_text)
    for m in _START_RE.finditer(content):
        positions.append((m.start(), int(m.group(1)), m.group(2)))

    segments: list[tuple[int, str]] = []
    for i, (offset, schuttenr, first_line_text) in enumerate(positions):
        # The segment text starts at the <start> element itself (we'll use the
        # inner text as the first line) and ends just before the next <start>
        # element, or at </root>.
        if i + 1 < len(positions):
            end_offset = positions[i + 1][0]
        else:
            # take up to </root>
            m_end = _END_RE.search(content, offset)
            end_offset = m_end.start() if m_end else len(content)

        # The raw block is everything from the end of this <start>…</start> tag
        # to the end offset.  We prepend the inner first-line text.
        m_this = _START_RE.search(content, offset)
        after_start_tag = content[m_this.end(): end_offset]

        # Prepend first line text and the trailing content
        raw_block = first_line_text + after_start_tag
        segments.append((schuttenr, raw_block))

    return segments


def _parse_lines(raw: str) -> list[str]:
    """Split raw block on <br> and return non-empty stripped lines."""
    # Strip any <page …> / </page> wrapper tags embedded in the block
    raw = re.sub(r"</?page[^>]*>", "", raw)
    # Split on <br> (with optional whitespace)
    parts = re.split(r"\s*<br\s*/?>\s*", raw)
    lines = []
    for part in parts:
        # Remove residual XML tags (e.g. stray <start>, </start>)
        clean = re.sub(r"<[^>]+>", "", part).strip()
        if clean:
            lines.append(clean)
    return lines


def _lemma_attrs(schuttenr: int, meta: dict[str, Any], corpus: str) -> str:
    """Build XML attribute string for the <lemma> element."""
    attrs = {
        "schuttenr": str(schuttenr),
        "corpus": corpus,
        "name": meta.get("name") or "",
        "givenname": meta.get("givenname") or "",
        "intraposition": meta.get("intraposition") or "",
        "beginjaar": str(meta.get("beginjaar") or ""),
        "eindjaar": str(meta.get("eindjaar") or ""),
        "functie": meta.get("functie") or "",
        "category": meta.get("category") or "",
        "url": meta.get("url") or "",
    }
    return " ".join(
        f'{k}="{sax.escape(v)}"' for k, v in attrs.items() if v
    )


def extract_lemmas(
    tagged_xml_path: Path,
    lemmas: list[dict[str, Any]],
    out_dir: Path,
    prefix: str,
    *,
    corpus: str = "",
    verbose: bool = False,
) -> dict[str, Any]:
    """Extract lemmas from a tagged XML file and write individual XML files.

    Parameters
    ----------
    tagged_xml_path:
        Output of tag_xml.tag_corpus().
    lemmas:
        Metadata list from read_excel.load_lemmas().
    out_dir:
        Directory where individual lemma files will be written.
    prefix:
        Filename prefix, e.g. ``'nl'`` or ``'bl'``.
    corpus:
        Value for the ``corpus`` attribute (defaults to *prefix*).
    verbose:
        Print progress.

    Returns
    -------
    dict with keys:
        extracted   - number of files written
        no_meta     - list of schuttenr values with no matching Excel row
        empty       - list of schuttenr values that produced zero lines
    """
    corpus = corpus or prefix
    meta_by_nr = {r["schuttenr"]: r for r in lemmas}

    raw = tagged_xml_path.read_bytes()
    try:
        content = raw.decode("utf-8")
    except UnicodeDecodeError:
        content = raw.decode("latin-1", errors="replace")

    segments = _split_at_starts(content)
    out_dir.mkdir(parents=True, exist_ok=True)

    stats: dict[str, Any] = {"extracted": 0, "no_meta": [], "empty": []}

    for schuttenr, raw_block in segments:
        lines = _parse_lines(raw_block)
        if not lines:
            stats["empty"].append(schuttenr)
            if verbose:
                print(f"  [empty] nr {schuttenr}")
            continue

        meta = meta_by_nr.get(schuttenr, {})
        if not meta:
            stats["no_meta"].append(schuttenr)
            if verbose:
                print(f"  [no-meta] nr {schuttenr}")

        attrs = _lemma_attrs(schuttenr, meta, corpus)
        lines_xml = "\n  ".join(
            f"<line>{sax.escape(line)}</line>" for line in lines
        )
        xml_out = (
            '<?xml version="1.0" encoding="utf-8"?>\n'
            f"<lemma {attrs}>\n"
            f"  {lines_xml}\n"
            "</lemma>\n"
        )

        fname = out_dir / f"{prefix}_{schuttenr:04d}.xml"
        fname.write_text(xml_out, encoding="utf-8")
        stats["extracted"] += 1
        if verbose:
            print(f"  [ok]  {fname.name}")

    return stats
