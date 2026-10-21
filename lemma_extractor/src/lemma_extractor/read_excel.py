"""Read lemma metadata from the Dijkstra Excel workbooks using pandas.

Returns a list of dicts with normalised keys, one per lemma row.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pandas as pd

SchutteNr = int | str


def parse_schutte_nr(raw: Any) -> SchutteNr | None:
    """Parse a spreadsheet schutte_nr / schuttenr value.

    Returns an int for normal numeric ids, or the stripped string for human
    adaptations such as ``418a`` (a variant entry under lemma 418).
    """
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return None
    if isinstance(raw, int):
        return raw
    if isinstance(raw, float) and raw == int(raw):
        return int(raw)
    s = str(raw).strip()
    if not s or s.lower() == "nan":
        return None
    try:
        return int(float(s))
    except ValueError:
        return s


def schutte_nr_sort_key(nr: SchutteNr) -> tuple:
    """Sort key so 418 precedes 418a."""
    if isinstance(nr, int):
        return (0, nr, "")
    m = re.match(r"^(\d+)(.*)$", str(nr))
    if m:
        return (0, int(m.group(1)), m.group(2))
    return (1, 0, str(nr))


def display_name_from_meta(meta: dict[str, Any] | None, fallback: str = "") -> str:
    """Build a lemma heading from Dijkstra name fields.

    Format: ``Surname, Givenname [intra] [post]`` (e.g. ``Aerssen, François van``).
    Falls back to *fallback* (typically TOC title with leading number stripped).
    """
    if not meta:
        return _strip_entry_nr(fallback)

    def _s(*keys: str) -> str:
        for k in keys:
            v = meta.get(k)
            if v is None or (isinstance(v, float) and pd.isna(v)):
                continue
            s = str(v).strip()
            if s and s.lower() != "nan":
                return s
        return ""

    name = _s("name")
    given = _s("givenname")
    intra = _s("Intraposition", "intraposition")
    post = _s("Postposition", "postposition")
    rest = " ".join(p for p in (intra, post) if p)

    if name and given:
        return f"{name}, {given}" + (f" {rest}" if rest else "")
    if name:
        return f"{name} {rest}".strip()
    if given:
        return f"{given} {rest}".strip()
    return _strip_entry_nr(fallback)


def _strip_entry_nr(title: str) -> str:
    return re.sub(r"^\d+[a-z]?\.\s*", "", title or "").strip() or (title or "")


def load_lemmas(excel_path: Path) -> list[dict[str, Any]]:
    """Load and normalise lemma rows from an Excel workbook.

    Returns records sorted by schuttenr (int or str, e.g. ``418a``).
    """
    df = pd.read_excel(excel_path, engine="openpyxl", dtype=str)
    df.columns = df.columns.str.strip()

    result = []
    for _, row in df.iterrows():
        nr_raw = row.get("schutte_nr") or row.get("schuttenr")
        schuttenr = parse_schutte_nr(nr_raw)
        if schuttenr is None:
            continue

        def _val(col: str, *fallbacks: str) -> str:
            for c in (col, *fallbacks):
                v = row.get(c)
                if v and not pd.isna(v):
                    return str(v).strip()
            return ""

        def _int_val(col: str) -> int | None:
            v = row.get(col)
            if v and not pd.isna(v):
                try:
                    return int(float(v))
                except (ValueError, TypeError):
                    pass
            return None

        result.append({
            "schuttenr": schuttenr,
            "name": _val("name"),
            "givenname": _val("givenname"),
            "intraposition": _val("Intraposition"),
            "postposition": _val("Postposition"),
            "pagenr": _int_val("pagenr"),
            "beginjaar": _val("schutte_beginjaar", "derived_beginjaar"),
            "eindjaar": _val("schutte_eindjaar", "derived_eindjaar"),
            "functie": _val("schutte_functie"),
            "category": _val("category"),
            "startregel": _int_val("startregel"),
            "start": _val("start"),
            "url": _val("url", "hyperlink"),
        })

    result.sort(key=lambda r: schutte_nr_sort_key(r["schuttenr"]))
    return result
