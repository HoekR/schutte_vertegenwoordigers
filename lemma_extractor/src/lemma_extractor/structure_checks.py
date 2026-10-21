"""Post-parse structure repairs from structure-gold findings.

Rules (gold-backed):
1. Genealogy starts with ``Zoon van`` / ``Dochter van`` / ``Uit dit huwelijk``.
2. Genealogy is contiguous blocks — no singleton islands.
3. Footnotes are contiguous blocks — no footnote↔body↔footnote flicker.
4. Attach regular bio cues (``geb.``, baptism ``ged.``, death cross ``f`` / ``t``)
   as line metadata without changing zones; year/month fragments on the next
   line after ``geb.``/``ged.`` get ``birth_continued``.

Applied after HTML(+hOCR) zoning via :func:`apply_structure_checks`.
"""

from __future__ import annotations

import re
from typing import Any

# Genealogy block openers (case-insensitive).
_GEN_START = re.compile(
    r"^(?:Zoon|Dochter)\s+van\b|^Uit dit huwelijk\b",
    re.IGNORECASE,
)
# End genealogy before these zones / cues.
_GEN_STOP_ZONES = frozenset(
    {"lemma_entry", "period_header", "chapter_intro", "footnote", "page_number"}
)
# Staff / sub-entry lines after family block (gold: bl:502 #48–58).
_SECRETARY = re.compile(
    r"^(?:"
    r"Secretaris|Hofmeester|Zijn hofmeester|Zijn klerk|Zijn secretaris|"
    r"Tot\s+\d{4}\s+was\s+secretaris|"
    r"Van\s+\d{4}\s+tot\s+\d{4}\s+was\s+"
    r")\b",
    re.IGNORECASE,
)
# Period / agent sub-heads after a blank (gold: bl:240 ``(1684)-1698 agent``).
_PERIOD_AGENT = re.compile(
    r"^\(?\d{4}\)?\s*[-–—]\s*\(?\d{4}\)?.*\bagent\b",
    re.IGNORECASE,
)
# Sources often trail genealogy on the same paragraph; soft_break ends the block.

_BIRTH = re.compile(r"\bgeb\.?\s", re.IGNORECASE)
# Baptism: "ged. Londen", "ged. 's-Gravenhage" (gold often tags as birth_date)
_BAPTISM = re.compile(r"\bged\.?\s", re.IGNORECASE)
# Death cross: "f Leiden", "f (onthoofd)", "t Parijs", "t na 12".
# Reject English title fragments: "tot f van Gloucester", "tot f;".
_DEATH_CROSS = re.compile(
    r"(?<!tot)(?:^|[\s,;])([ft])\s+(?:\(|(?:na|vóór|voor)\s+)?[A-ZÀ-Ü'0-9]",
    re.IGNORECASE,
)
# Next-line birth fragments after geb./ged. (gold: "1601", "mei", "1618/1619").
# May share a line with baptism, e.g. bl:240 ``mei, ged. aldaar … 14 mei 1596508``.
_BIRTH_CONTINUED = re.compile(
    r"^(?:"
    r"\d{4}(?:\s*/\s*\d{2,4})?"  # year or year/year
    r"|\d{4}\d{1,4}"  # year + glued footnote digits
    r"|(?:jan(?:uari)?|febr?(?:uari)?|maart|mrt|apr(?:il)?|mei|"
    r"jun(?:i)?|jul(?:i)?|aug(?:ustus)?|sept?(?:ember)?|"
    r"okt(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
    r")\b",
    re.IGNORECASE,
)
# Schutte year (15xx–18xx) immediately followed by footnote digits: 1596508 → 1596 + 508.
_FOOTNOTE_GLUE_YEAR = re.compile(r"\b(1[5-8]\d{2})(\d{2,4})\b")
_BIRTH_OPENERS = frozenset({"birth", "baptism"})


def _text(ln: dict[str, Any]) -> str:
    return (ln.get("text") or "").strip()


def _is_gap(zone: str) -> bool:
    return zone in ("blank", "soft_break")


def annotate_bio_cues(lines: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Attach ``bio_cues`` for geb./ged./death-cross, birth continuations, footnote glue."""
    out: list[dict[str, Any]] = []
    for ln in lines:
        row = dict(ln)
        cues: list[str] = []
        t = _text(row)
        if _BIRTH.search(t):
            cues.append("birth")
        if _BAPTISM.search(t):
            cues.append("baptism")
        if _DEATH_CROSS.search(t):
            cues.append("death_cross")
        if _FOOTNOTE_GLUE_YEAR.search(t):
            cues.append("footnote_glue")
        if cues:
            row["bio_cues"] = cues
        out.append(row)

    # Propagate birth_continued onto the next non-gap line after geb./ged.
    # Allowed together with baptism (month starts the line; ged./year follow).
    prev_birth = False
    for row in out:
        z = row.get("zone") or ""
        if _is_gap(z):
            continue
        cues = list(row.get("bio_cues") or [])
        t = _text(row)
        if prev_birth and "birth_continued" not in cues:
            if (
                t
                and not _GEN_START.match(t)
                and "birth" not in cues
                and _BIRTH_CONTINUED.match(t)
            ):
                cues.append("birth_continued")
                row["bio_cues"] = cues
        prev_birth = bool(_BIRTH_OPENERS.intersection(cues))
    return out


def _genealogy_stop_text(t: str) -> bool:
    """True if this line ends a Zoon-block (secretary / period-agent sub-entry)."""
    return bool(_SECRETARY.match(t) or _PERIOD_AGENT.match(t))


def repair_genealogy_blocks(lines: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Re-zone genealogy to Zoon-/Dochter-/Uit-dit-huwelijk-started contiguous runs.

    Soft breaks end the block (bl:240 agent sub-head; bl:502 secretaris run after
    sources). Secretary / period-agent lines also stop, any zone.
    """
    out = [dict(ln) for ln in lines]
    n = len(out)
    # Mark membership in a true genealogy span.
    in_block = [False] * n
    i = 0
    while i < n:
        if _is_gap(out[i].get("zone") or ""):
            i += 1
            continue
        if _GEN_START.match(_text(out[i])):
            # Always claim the opener (even if mis-zoned chapter_intro / lemma_entry
            # — those are also stop zones for *continuation*, which used to leave
            # i==j and spin forever, e.g. NL 0037).
            in_block[i] = True
            j = i + 1
            while j < n:
                z = out[j].get("zone") or ""
                if _is_gap(z):
                    # Paragraph break → end family/sources block (do not leap).
                    break
                if z in _GEN_STOP_ZONES:
                    break
                t = _text(out[j])
                if _genealogy_stop_text(t):
                    break
                in_block[j] = True
                j += 1
            i = j
        else:
            i += 1

    for i, ln in enumerate(out):
        z = ln.get("zone") or ""
        if _is_gap(z):
            continue
        if in_block[i]:
            if z != "genealogy":
                ln["zone_orig"] = ln.get("zone_orig", z)
                ln["zone"] = "genealogy"
                ln["zone_reason"] = "gen_block_from_zoon"
        elif z == "genealogy":
            ln["zone_orig"] = ln.get("zone_orig", z)
            ln["zone"] = "body"
            ln["zone_reason"] = "gen_orphan_demote"
    return out


def repair_footnote_blocks(lines: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Fill body/genealogy gaps between footnotes; avoid body↔footnote flicker.

    Between two ``footnote`` lines, only ``body`` / ``genealogy`` / ``blank`` may
    appear — those are re-zoned to ``footnote`` (gold: body_as_footnote mid-notes).
    """
    out = [dict(ln) for ln in lines]
    fn_idx = [i for i, ln in enumerate(out) if ln.get("zone") == "footnote"]
    if len(fn_idx) < 2:
        return out

    fillable = frozenset({"body", "genealogy", "blank", "soft_break"})
    for a, b in zip(fn_idx, fn_idx[1:]):
        gap = out[a + 1 : b]
        if not gap:
            continue
        if all((ln.get("zone") or "") in fillable for ln in gap):
            for ln in gap:
                z = ln.get("zone") or ""
                if _is_gap(z):
                    continue
                if z != "footnote":
                    ln["zone_orig"] = ln.get("zone_orig", z)
                    ln["zone"] = "footnote"
                    ln["zone_reason"] = "fn_block_fill"
    return out


def apply_structure_checks(lines: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Run all structure repairs in order; return new line list."""
    out = annotate_bio_cues(lines)
    out = repair_genealogy_blocks(out)
    out = repair_footnote_blocks(out)
    return out
