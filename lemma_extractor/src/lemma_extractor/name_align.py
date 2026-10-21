"""Token alignment for Schutte person names (formulation-style Lev + SW/DAG + MSA).

Mirrors ``formulation.boundary.align_sw`` / ``align_dag``:

- **Word score** = classic relative Levenshtein (rapidfuzz ``normalized_similarity``)
- **SW** = Smith-Waterman local alignment over name tokens
- **DAG** = layered slot-cloud DP with optional particle/title skips
- **MSA** = progressive pairwise Needleman-Wunsch (2- or 3-way: Excel/TOC/persons)

Formulation deferred full MSA for formula slot-clouds; for short name strings
MSA is cheap and useful when three headers disagree.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from lemma_extractor.name_sim import lev_ratio, norm_name

# Match score scaling (same as formulation.boundary.align_sw)
_MATCH_LO = -1.5
_MATCH_HI = 1.5  # sim=1 → (1*3)-1.5


def tokenize_name(s: str) -> list[str]:
    return [t for t in norm_name(s).split() if t]


def word_similarity(w1: str, w2: str) -> float:
    """Relative Levenshtein similarity in ``[0, 1]`` (formulation ``word_similarity``)."""
    return lev_ratio(w1, w2)


def _match_score(sim: float) -> float:
    return (sim * 3.0) - 1.5


# Particles / titles often optional when aligning Excel ↔ short TOC.
_OPTIONAL_TOKENS = frozenset(
    {
        "van",
        "de",
        "den",
        "der",
        "des",
        "het",
        "la",
        "le",
        "du",
        "von",
        "mr",
        "heer",
        "baron",
        "graaf",
        "ridder",
        "comte",
        "comtesse",
        "marquis",
    }
)


@dataclass(frozen=True)
class AlignResult:
    method: str
    score: float  # normalized [0, 1]
    raw_score: float
    matched_pairs: tuple[tuple[str, str], ...] = ()


def align_sw(
    template: list[str],
    query: list[str],
    *,
    gap_penalty: float = 1.0,
) -> AlignResult:
    """Smith-Waterman over tokens; score normalized by best possible diagonal."""
    m, n = len(template), len(query)
    if m == 0 or n == 0:
        return AlignResult("sw", 0.0, 0.0)
    H = np.zeros((m + 1, n + 1))
    max_score = 0.0
    max_pos = (0, 0)
    for i in range(1, m + 1):
        for j in range(1, n + 1):
            sim = word_similarity(template[i - 1], query[j - 1])
            match = H[i - 1, j - 1] + _match_score(sim)
            delete = H[i - 1, j] - gap_penalty
            insert = H[i, j - 1] - gap_penalty
            H[i, j] = max(0.0, match, delete, insert)
            if H[i, j] > max_score:
                max_score = float(H[i, j])
                max_pos = (i, j)
    # Traceback pairs
    i, j = max_pos
    pairs_rev: list[tuple[str, str]] = []
    while i > 0 and j > 0 and H[i, j] > 0:
        sim = word_similarity(template[i - 1], query[j - 1])
        match = H[i - 1, j - 1] + _match_score(sim)
        delete = H[i - 1, j] - gap_penalty
        insert = H[i, j - 1] - gap_penalty
        cell = H[i, j]
        if abs(cell - match) <= 1e-9 and match >= delete and match >= insert:
            pairs_rev.append((template[i - 1], query[j - 1]))
            i -= 1
            j -= 1
        elif abs(cell - delete) <= 1e-9 and delete >= insert:
            i -= 1
        else:
            j -= 1
    pairs_rev.reverse()
    denom = _MATCH_HI * min(m, n)
    norm = max(0.0, min(1.0, max_score / denom)) if denom > 0 else 0.0
    return AlignResult("sw", norm, max_score, tuple(pairs_rev))


def align_dag(
    template: list[str],
    query: list[str],
    *,
    gap_penalty: float = 1.0,
    optional_tokens: frozenset[str] | None = None,
) -> AlignResult:
    """DAG / Viterbi over template layers × query tokens (formulation ``align_dag``).

    Each template token is a layer (single-variant slot). Particles/titles in
    ``optional_tokens`` get a skip node so Excel honorifics can drop vs short TOC.
    """
    opt = optional_tokens if optional_tokens is not None else _OPTIONAL_TOKENS
    m, n = len(template), len(query)
    if m == 0 or n == 0:
        return AlignResult("dag", 0.0, 0.0)

    # layers[i] = list of (token, is_skip)
    layers: list[list[tuple[str, bool]]] = []
    for tok in template:
        layer = [(tok, False)]
        if tok in opt:
            layer.append(("", True))
        layers.append(layer)

    DP = np.zeros((m + 1, n + 1))
    max_score = 0.0
    for layer_i in range(1, m + 1):
        nodes = layers[layer_i - 1]
        for j in range(1, n + 1):
            ocr = query[j - 1]
            best_node = -1.0
            for tok, is_skip in nodes:
                if is_skip:
                    sim_score = 0.0
                else:
                    sim_score = _match_score(word_similarity(tok, ocr))
                if sim_score > best_node:
                    best_node = sim_score
            match = DP[layer_i - 1, j - 1] + best_node
            deletion = DP[layer_i - 1, j] - (
                0.0 if any(s for _, s in nodes) else gap_penalty
            )
            insertion = DP[layer_i, j - 1] - gap_penalty
            score = max(0.0, match, deletion, insertion)
            DP[layer_i, j] = score
            if score > max_score:
                max_score = float(score)

    denom = _MATCH_HI * min(m, n)
    norm = max(0.0, min(1.0, max_score / denom)) if denom > 0 else 0.0
    return AlignResult("dag", norm, max_score)


def align_nw(
    a: list[str],
    b: list[str],
    *,
    gap_penalty: float = 1.0,
) -> AlignResult:
    """Global Needleman-Wunsch (pairwise MSA building block)."""
    m, n = len(a), len(b)
    if m == 0 and n == 0:
        return AlignResult("nw", 1.0, 0.0)
    if m == 0 or n == 0:
        return AlignResult("nw", 0.0, 0.0)
    H = np.zeros((m + 1, n + 1))
    for i in range(1, m + 1):
        H[i, 0] = -gap_penalty * i
    for j in range(1, n + 1):
        H[0, j] = -gap_penalty * j
    for i in range(1, m + 1):
        for j in range(1, n + 1):
            sim = word_similarity(a[i - 1], b[j - 1])
            match = H[i - 1, j - 1] + _match_score(sim)
            delete = H[i - 1, j] - gap_penalty
            insert = H[i, j - 1] - gap_penalty
            H[i, j] = max(match, delete, insert)
    raw = float(H[m, n])
    # Normalize: perfect = 1.5 * aligned length; use max(m,n) as length
    denom = _MATCH_HI * max(m, n)
    # Shift raw from [-gap*len, +1.5*min] into [0,1]
    norm = max(0.0, min(1.0, (raw + gap_penalty * max(m, n)) / (denom + gap_penalty * max(m, n))))
    return AlignResult("nw", norm, raw)


def msa_pairwise_similarity(*names: str) -> float:
    """Progressive pairwise MSA similarity for 2+ name strings.

    For two names: Needleman-Wunsch token alignment (global).
    For three+: mean of all pairwise NW scores (Star-MSA without building
    an explicit consensus column string — enough for header agreement).
    """
    toks = [tokenize_name(n) for n in names if norm_name(n)]
    toks = [t for t in toks if t]
    if len(toks) < 2:
        return 0.0
    if len(toks) == 2:
        return align_nw(toks[0], toks[1]).score
    scores: list[float] = []
    for i in range(len(toks)):
        for j in range(i + 1, len(toks)):
            scores.append(align_nw(toks[i], toks[j]).score)
    return float(sum(scores) / len(scores))


def name_alignment_scores(a: str, b: str) -> dict[str, float]:
    """SW + DAG (+ sorted variants) alignment scores in ``[0, 1]``."""
    ta, tb = tokenize_name(a), tokenize_name(b)
    if not ta or not tb:
        return {"sw": 0.0, "dag": 0.0, "sw_sort": 0.0, "dag_sort": 0.0, "nw": 0.0}
    sa, sb = sorted(ta), sorted(tb)
    return {
        "sw": align_sw(ta, tb).score,
        "dag": align_dag(ta, tb).score,
        "sw_sort": align_sw(sa, sb).score,
        "dag_sort": align_dag(sa, sb).score,
        "nw": align_nw(ta, tb).score,
    }
