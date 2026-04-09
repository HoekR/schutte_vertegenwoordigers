"""
Phase 4b — Export fully-enriched data to JSON files.

Writes four files into ``output_dir``:
  lemmas_nl.json    — list of enriched NL lemma dicts
  lemmas_bl.json    — list of enriched BL lemma dicts
  persons.json      — combined person index (NL + BL)
  geo.json          — combined geographic index (NL + BL)

The JSON is UTF-8 encoded and pretty-printed for readability.  Each file is
a top-level JSON array.
"""

from __future__ import annotations

import json
from pathlib import Path


def export(
    nl_lemmas: list[dict],
    bl_lemmas: list[dict],
    persons_index: list[dict],
    geo_index: list[dict],
    output_dir: Path,
) -> None:
    """Write enriched data to JSON files in ``output_dir``.

    Parameters
    ----------
    nl_lemmas, bl_lemmas:
        Enriched lemma lists from ``build_refs.build_refs()``.
    persons_index:
        Enriched person list from ``build_refs.build_refs()``.
    geo_index:
        Enriched geo list from ``build_refs.build_refs()``.
    output_dir:
        Target directory.  Created if it does not exist.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    files = {
        'lemmas_nl.json': nl_lemmas,
        'lemmas_bl.json': bl_lemmas,
        'persons.json': persons_index,
        'geo.json': geo_index,
    }

    for filename, data in files.items():
        target = output_dir / filename
        target.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding='utf-8',
        )
        print(f'  Wrote {target}  ({len(data)} records)')
