"""Insert <start schuttenr="N"> markers into a corpus XML file.

Strategy
--------
- Read the XML as text (detect encoding from the file).
- For each lemma (sorted by schuttenr), find the `start` text in the content
  and wrap it: `<start schuttenr="N">{text}</start>`.
- Skip lemmas whose tag is already present.
- Try four match variants (exact / stripped / double-encoded / both) to cope
  with mixed encoding artefacts in the source files.

Double-encoding artefact: the binnenland XML was saved as a Latin-1 file
that had already been decoded from UTF-8, producing sequences like
  é → UTF-8 bytes C3 A9 → read as Latin-1 → "Ã©"
The `start` column in the Excel has the original correct unicode. We therefore
also try encoding the search string with this transformation before giving up.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any


def _cp1252_mangle(text: str) -> str:
    """One round of cp1252 mangling: encode as UTF-8, decode as cp1252.

    'é' (U+00E9)  →  UTF-8 C3 A9  →  cp1252 decode  →  'Ã©'
    This matches files that were saved as UTF-8 but processed through cp1252 once.
    """
    try:
        return text.encode("utf-8").decode("cp1252")
    except (UnicodeDecodeError, UnicodeEncodeError):
        return text


def _cp1252_mangle2(text: str) -> str:
    """Two rounds of cp1252 mangling.

    'é'  →  'Ã©'  →  'ÃƒÂ©'
    This matches files processed through cp1252 twice (e.g. binnenland tagged XML).
    """
    return _cp1252_mangle(_cp1252_mangle(text))


def _normalise_ws(text: str) -> str:
    """Collapse runs of whitespace to a single space."""
    return re.sub(r"\s+", " ", text).strip()


def _read_xml(path: Path) -> str:
    """Read XML file, trying UTF-8 first, then cp1252."""
    raw = path.read_bytes()
    m = re.search(rb'encoding=["\']([^"\']+)["\']', raw[:200])
    if m:
        enc = m.group(1).decode("ascii")
        return raw.decode(enc, errors="replace")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("cp1252", errors="replace")


def tag_corpus(
    xml_path: Path,
    lemmas: list[dict[str, Any]],
    out_path: Path,
    *,
    verbose: bool = False,
) -> dict[str, Any]:
    """Write a copy of *xml_path* with ``<start schuttenr="N">`` markers inserted.

    Returns a statistics dict:
        tagged     - number of new markers inserted
        skipped    - lemmas already present in input (no-op)
        not_found  - list of schuttenr values whose start text was not located
    """
    content = _read_xml(xml_path)
    stats: dict[str, Any] = {"tagged": 0, "skipped": 0, "not_found": []}

    for lemma in sorted(lemmas, key=lambda r: r["schuttenr"]):
        schuttenr = lemma["schuttenr"]
        start_text = (lemma.get("start") or "").strip()

        if not start_text:
            stats["not_found"].append(schuttenr)
            if verbose:
                print(f"  [skip]  nr {schuttenr}: empty start text")
            continue

        marker = f'schuttenr="{schuttenr}"'
        if marker in content:
            stats["skipped"] += 1
            if verbose:
                print(f"  [skip]  nr {schuttenr}: already tagged")
            continue

        # Build search variants in order of preference.
        # Each variant is tried as an exact string first (fast path).
        # Then we try a regex that allows \s+ between tokens (handles extra spaces).
        _m1 = _cp1252_mangle(start_text)
        _m2 = _cp1252_mangle2(start_text)
        exact_variants = list(dict.fromkeys(filter(None, [
            start_text, _m1, _m2,
        ])))

        found = False
        for variant in exact_variants:
            if variant in content:
                wrapped = f'<start schuttenr="{schuttenr}">{variant}</start>'
                content = content.replace(variant, wrapped, 1)
                stats["tagged"] += 1
                if verbose:
                    print(f"  [ok]   nr {schuttenr}: tagged '{variant[:60]}'")
                found = True
                break

        if not found:
            # Whitespace-flexible regex search: replace each run of spaces/tabs
            # in the escaped pattern with \s+ so "7.   Gideon" matches "7. Gideon".
            for variant in exact_variants:
                pattern = re.sub(r"\s+", r"\\s+", re.escape(variant))
                try:
                    m = re.search(pattern, content)
                except re.error:
                    continue
                if m:
                    original = m.group(0)
                    wrapped = f'<start schuttenr="{schuttenr}">{original}</start>'
                    content = content.replace(original, wrapped, 1)
                    stats["tagged"] += 1
                    if verbose:
                        print(f"  [ok-ws] nr {schuttenr}: tagged '{original[:60]}'")
                    found = True
                    break

        if not found:
            stats["not_found"].append(schuttenr)
            if verbose:
                print(
                    f"  [miss] nr {schuttenr}: "
                    f"'{start_text[:60]}' not found in XML"
                )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(content, encoding="utf-8")
    return stats
