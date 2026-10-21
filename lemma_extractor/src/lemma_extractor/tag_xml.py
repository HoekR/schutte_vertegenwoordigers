"""Insert <start schuttenr="N"> markers into a corpus XML file.

Strategy
--------
- Read the XML as text (detect encoding from the file).
- For each lemma (sorted by schuttenr), find the `start` text in the content
  and wrap it: `<start schuttenr="N">{text}</start>`.
- Skip lemmas whose tag is already present.
- Try encoding variants (exact / demangled Excel / cp1252+latin-1 mangling)
  and whitespace-flexible regex, then a lemma-nr + ASCII fingerprint fallback.

Encoding artefacts:
- Excel may already contain mojibake (``FranÃ§ois``) while XML has Unicode.
- Binnenland tagged XML often has triple mojibake (``latin-1 ×2 + cp1252``).
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from lemma_extractor.read_excel import schutte_nr_sort_key


def _cp1252_mangle(text: str) -> str:
    """One round of cp1252 mangling: encode as UTF-8, decode as cp1252."""
    try:
        return text.encode("utf-8").decode("cp1252")
    except (UnicodeDecodeError, UnicodeEncodeError):
        return text


def _cp1252_mangle2(text: str) -> str:
    """Two rounds of cp1252 mangling (``é`` → ``ÃƒÂ©``)."""
    return _cp1252_mangle(_cp1252_mangle(text))


def _nl_triple_mangle(text: str) -> str:
    """Match binnenland tagged XML: latin-1, latin-1, then cp1252."""
    s = text
    for codec in ("latin-1", "latin-1", "cp1252"):
        try:
            s = s.encode("utf-8").decode(codec)
        except (UnicodeDecodeError, UnicodeEncodeError):
            return text
    return s


def _demangle(text: str) -> str:
    """Reverse one mojibake layer (Excel ``FranÃ§ois`` → ``François``)."""
    for codec in ("cp1252", "latin-1"):
        try:
            return text.encode(codec).decode("utf-8")
        except (UnicodeDecodeError, UnicodeEncodeError):
            continue
    return text


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


def _start_variants(start_text: str) -> list[str]:
    """Build unique search strings for a lemma start line."""
    dem = _demangle(start_text)
    variants = [
        start_text,
        dem,
        _cp1252_mangle(start_text),
        _cp1252_mangle2(start_text),
        _nl_triple_mangle(start_text),
        _cp1252_mangle(dem),
        _cp1252_mangle2(dem),
        _nl_triple_mangle(dem),
    ]
    return list(dict.fromkeys(v for v in variants if v))


def _ws_flexible_pattern(variant: str) -> str:
    """Escape *variant* but allow flexible whitespace; digits may be glued."""
    # Split on whitespace; between tokens allow \\s* (Excel "1644 1249" ↔ XML "16441249")
    parts = re.split(r"\s+", variant.strip())
    return r"\s*".join(re.escape(p) for p in parts if p)


def _nr_fingerprint_pattern(schuttenr: Any, start_text: str) -> str | None:
    """Fallback: ``N.\\s+`` + first distinctive ASCII word from the start line."""
    m = re.match(r"^(\d+)\.\s*(.*)$", start_text.strip())
    if not m:
        return None
    nr, rest = m.group(1), m.group(2)
    if str(schuttenr) != nr and not str(schuttenr).startswith(nr):
        # still use Excel nr prefix when present
        nr = str(schuttenr) if isinstance(schuttenr, int) else nr
    words = re.findall(r"[A-Za-z]{3,}", rest)
    if not words:
        return None
    # Prefer a name-like token (not Mr/van/de)
    skip = {"van", "den", "der", "des", "het", "the", "and", "als", "mr", "heer"}
    pick = next((w for w in words if w.lower() not in skip), words[0])
    return rf'(?<![0-9"]){re.escape(str(nr))}\.\s+[^\n<]{{0,120}}?{re.escape(pick)}'


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

    for lemma in sorted(lemmas, key=lambda r: schutte_nr_sort_key(r["schuttenr"])):
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

        exact_variants = _start_variants(start_text)
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
            for variant in exact_variants:
                pattern = _ws_flexible_pattern(variant)
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
            fp = _nr_fingerprint_pattern(schuttenr, start_text)
            if fp:
                # Prefer demangled fingerprint search on demangled rest too
                for seed in (start_text, _demangle(start_text)):
                    fp = _nr_fingerprint_pattern(schuttenr, seed)
                    if not fp:
                        continue
                    try:
                        m = re.search(fp, content)
                    except re.error:
                        continue
                    if m:
                        # Wrap from lemma nr through end of matched span's first line chunk
                        original = m.group(0)
                        # Extend to end of line (before <br>) when match is a prefix
                        end = m.end()
                        br = content.find("<br", end)
                        if br != -1 and br - end < 200:
                            original = content[m.start() : br]
                        else:
                            original = content[m.start() : end]
                        wrapped = f'<start schuttenr="{schuttenr}">{original}</start>'
                        content = content.replace(original, wrapped, 1)
                        stats["tagged"] += 1
                        if verbose:
                            print(f"  [ok-fp] nr {schuttenr}: tagged '{original[:60]}'")
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
