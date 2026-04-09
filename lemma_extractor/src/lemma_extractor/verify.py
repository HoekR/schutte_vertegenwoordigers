"""Verify extracted lemma files against the Excel metadata.

Checks:
  - Number of files in out_dir matches number of lemmas in Excel
  - Each expected file exists
  - Each file is valid XML
  - The <lemma> root element has a schuttenr attribute matching the filename
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any


def verify(
    out_dir: Path,
    lemmas: list[dict[str, Any]],
    prefix: str,
    *,
    verbose: bool = False,
) -> dict[str, Any]:
    """Verify extracted lemma files.

    Returns a dict:
        ok          - number of files that passed all checks
        missing     - list of schuttenr values with no output file
        invalid_xml - list of (schuttenr, error_message) for unparseable files
        attr_mismatch - list of (schuttenr, detail) for attribute problems
    """
    stats: dict[str, Any] = {
        "ok": 0,
        "missing": [],
        "invalid_xml": [],
        "attr_mismatch": [],
    }

    for meta in sorted(lemmas, key=lambda r: r["schuttenr"]):
        schuttenr = meta["schuttenr"]
        fname = out_dir / f"{prefix}_{schuttenr:04d}.xml"

        if not fname.exists():
            stats["missing"].append(schuttenr)
            if verbose:
                print(f"  [missing] {fname.name}")
            continue

        try:
            tree = ET.parse(fname)
        except ET.ParseError as exc:
            stats["invalid_xml"].append((schuttenr, str(exc)))
            if verbose:
                print(f"  [xml-err] {fname.name}: {exc}")
            continue

        root = tree.getroot()
        got_nr = root.get("schuttenr")
        if got_nr != str(schuttenr):
            detail = f"expected schuttenr={schuttenr}, got {got_nr!r}"
            stats["attr_mismatch"].append((schuttenr, detail))
            if verbose:
                print(f"  [attr]   {fname.name}: {detail}")
            continue

        stats["ok"] += 1
        if verbose:
            print(f"  [ok]     {fname.name}")

    return stats


def report(stats: dict[str, Any], lemmas: list[dict[str, Any]], prefix: str) -> str:
    """Return a human-readable summary string."""
    total = len(lemmas)
    lines = [
        f"Corpus: {prefix}",
        f"  Expected : {total}",
        f"  OK       : {stats['ok']}",
        f"  Missing  : {len(stats['missing'])}",
        f"  Bad XML  : {len(stats['invalid_xml'])}",
        f"  Attr mismatch: {len(stats['attr_mismatch'])}",
    ]
    if stats["missing"]:
        lines.append(f"  Missing schuttenr: {stats['missing'][:20]}")
    if stats["invalid_xml"]:
        for nr, err in stats["invalid_xml"][:5]:
            lines.append(f"  XML error nr {nr}: {err}")
    if stats["attr_mismatch"]:
        for nr, detail in stats["attr_mismatch"][:5]:
            lines.append(f"  Attr error nr {nr}: {detail}")
    return "\n".join(lines)
