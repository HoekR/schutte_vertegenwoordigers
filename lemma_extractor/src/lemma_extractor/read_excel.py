"""Read lemma metadata from the Dijkstra Excel workbooks using pandas.

Returns a list of dicts with normalised keys, one per lemma row.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd


def load_lemmas(excel_path: Path) -> list[dict[str, Any]]:
    """Load and normalise lemma rows from an Excel workbook.

    Returns records sorted by schuttenr (int).
    """
    df = pd.read_excel(excel_path, engine="openpyxl", dtype=str)
    df.columns = df.columns.str.strip()

    result = []
    for _, row in df.iterrows():
        nr_raw = row.get("schuttenr") or row.get("schutte_nr")
        if pd.isna(nr_raw) or not nr_raw:
            continue
        try:
            schuttenr = int(float(nr_raw))
        except (ValueError, TypeError):
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

    result.sort(key=lambda r: r["schuttenr"])
    return result
