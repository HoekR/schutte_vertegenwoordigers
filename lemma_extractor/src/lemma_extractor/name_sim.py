"""Person-name similarity for Schutte headers (Excel ↔ TOC / persons / entry).

Stack:
1. Marijn Koolen ``FuzzySearcher`` char/ngram + **rapidfuzz** classic relative
   Levenshtein on raw + token-sorted strings
2. Formulation-style **Levenshtein + Smith-Waterman / DAG** token alignment
   (``name_align``; word scores also rapidfuzz)
3. **MSA**: progressive pairwise Needleman-Wunsch (2-way in ``name_similarity``;
   3-way Excel/TOC/persons via ``name_similarity_msa``)

See ``docs/name_similarity_benchmark.md``.
"""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Any

from fuzzy_search.fuzzy_searcher import FuzzySearcher
from rapidfuzz.distance import Levenshtein as RapidLevenshtein

_NON_WORD = re.compile(r"[^\w\s]", re.UNICODE)
_WS = re.compile(r"\s+")


@lru_cache(maxsize=1)
def _searcher() -> FuzzySearcher:
    return FuzzySearcher(
        char_match_threshold=0.5,
        ngram_threshold=0.5,
        levenshtein_threshold=0.5,
    )


def lev_ratio(a: str, b: str) -> float:
    """Classic relative Levenshtein ``1 - d / max(len)`` via rapidfuzz (not indel ratio)."""
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return float(RapidLevenshtein.normalized_similarity(a, b))


def norm_name(s: str) -> str:
    t = (s or "").lower()
    t = _NON_WORD.sub(" ", t)
    return _WS.sub(" ", t).strip()


def token_sort_name(s: str) -> str:
    return " ".join(sorted(norm_name(s).split()))


def _fuzzy_bag_scores(a: str, b: str, *, ngram_size: int = 2) -> list[float]:
    na, nb = norm_name(a), norm_name(b)
    if not na or not nb:
        return [0.0]
    fs = _searcher()
    sa, sb = token_sort_name(a), token_sort_name(b)
    ta, tb = set(na.split()), set(nb.split())

    def _combo(x: str, y: str) -> float:
        return (
            fs.score_char_overlap_ratio(x, y)
            + fs.score_ngram_overlap_ratio(x, y, ngram_size)
            + lev_ratio(x, y)
        ) / 3.0

    scores = [
        _combo(na, nb),
        _combo(sa, sb),
        lev_ratio(na, nb),
        lev_ratio(sa, sb),
    ]
    if ta and tb:
        shorter, longer = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
        if len(shorter) >= 2 and shorter <= longer:
            scores.append(0.92)
        else:
            scores.append(len(shorter & longer) / len(shorter | longer))
    return scores


def name_similarity(a: str, b: str, *, ngram_size: int = 2) -> float:
    """Similarity in ``[0, 1]``: FuzzySearcher+rapidfuzz bag + Lev/SW/DAG + MSA."""
    na, nb = norm_name(a), norm_name(b)
    if not na or not nb:
        return 0.0
    # Lazy import avoids cycle with name_align → name_sim
    from lemma_extractor.name_align import msa_pairwise_similarity, name_alignment_scores

    scores = list(_fuzzy_bag_scores(a, b, ngram_size=ngram_size))
    align = name_alignment_scores(a, b)
    scores.extend(align.values())
    scores.append(msa_pairwise_similarity(a, b))
    return max(scores)


def name_similarity_msa(*names: str) -> float:
    """Multi-source MSA agreement (Excel / TOC / persons).

    Progressive pairwise NW over name tokens; mean of all pairs.
    """
    from lemma_extractor.name_align import msa_pairwise_similarity

    cleaned = [n for n in names if norm_name(n or "")]
    if len(cleaned) < 2:
        return 0.0
    return msa_pairwise_similarity(*cleaned)


def name_similarity_detail(a: str, b: str) -> dict[str, Any]:
    """Breakdown of bag + alignment + MSA scores (for audits / UI)."""
    from lemma_extractor.name_align import msa_pairwise_similarity, name_alignment_scores

    bag = _fuzzy_bag_scores(a, b)
    align = name_alignment_scores(a, b)
    msa = msa_pairwise_similarity(a, b)
    parts = {
        "fuzzy_bag_max": max(bag) if bag else 0.0,
        **align,
        "msa_nw": msa,
    }
    parts["total"] = max(parts.values()) if parts else 0.0
    return parts


# Default pass threshold (same band as former SequenceMatcher 0.55).
DEFAULT_NAME_THRESHOLD = 0.55
