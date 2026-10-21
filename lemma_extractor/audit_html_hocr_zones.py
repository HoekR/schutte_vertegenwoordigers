#!/usr/bin/env python3
"""Step 1 of HYBRID_PLAN — audit HTML vs hOCR zone classification.

Aligns lines by fuzzy text match (not position zip), then reports:
  - zone agreement rate
  - critical disagreements: lemma_entry ↔ footnote
  - unmatched lines on either side

Usage:
  uv run python audit_html_hocr_zones.py --corpus nl --pages 20
  uv run python audit_html_hocr_zones.py --corpus all --pages 0   # all pages
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
from collections import Counter
from difflib import SequenceMatcher
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from lemma_extractor.parse_html import parse_page as html_parse  # noqa: E402
from lemma_extractor.parse_hocr import parse_page as hocr_parse  # noqa: E402
from lemma_extractor.zone_correct import correct_page_pair  # noqa: E402

CORPORA = {
    "nl": {
        "html_dir": ROOT / "schutte_binnenland",
        "hocr_dir": ROOT / "schutte_binnenland_ocr",
        "prefix": "schutte_nederlandsevertegenwoordigersinbuitenland",
    },
    "bl": {
        "html_dir": ROOT / "schutte_buitenland",
        "hocr_dir": ROOT / "schutte_buitenland_ocr",
        "prefix": "schutte_buitenlandsevertegenwoordigersinnederland",
    },
}

_SKIP = frozenset({"blank", "page_number"})
_NORM = re.compile(r"\s+")
# Critical for the "missing first line" / footnote bug
_CRITICAL = frozenset({("lemma_entry", "footnote"), ("footnote", "lemma_entry")})


def _norm(text: str) -> str:
    return _NORM.sub(" ", text).strip().lower()


def _kept(lines: list[dict]) -> list[dict]:
    return [ln for ln in lines if ln["zone"] not in _SKIP and ln.get("text")]


def _align(html_lines: list[dict], hocr_lines: list[dict], min_ratio: float = 0.55):
    """Greedy sequential align: for each HTML line, take best unused hOCR near cursor."""
    used: set[int] = set()
    pairs: list[tuple[dict | None, dict | None, float]] = []
    j0 = 0
    window = 8

    for h in html_lines:
        ht = _norm(h["text"])
        best_j, best_r = None, 0.0
        lo = max(0, j0 - 2)
        hi = min(len(hocr_lines), j0 + window)
        for j in range(lo, hi):
            if j in used:
                continue
            r = SequenceMatcher(None, ht, _norm(hocr_lines[j]["text"])).ratio()
            if r > best_r:
                best_r, best_j = r, j
        if best_j is not None and best_r >= min_ratio:
            used.add(best_j)
            pairs.append((h, hocr_lines[best_j], best_r))
            j0 = best_j + 1
        else:
            pairs.append((h, None, 0.0))

    for j, o in enumerate(hocr_lines):
        if j not in used:
            pairs.append((None, o, 0.0))
    return pairs


def _page_pairs(cfg: dict) -> list[tuple[Path, Path]]:
    html_files = sorted(cfg["html_dir"].glob(f"{cfg['prefix']}_*.html"))
    out = []
    for hp in html_files:
        op = cfg["hocr_dir"] / hp.name.replace(".html", ".hocr")
        if op.exists():
            out.append((hp, op))
    return out


def audit_corpus(corpus: str, max_pages: int, out_dir: Path) -> dict:
    cfg = CORPORA[corpus]
    pages = _page_pairs(cfg)
    if max_pages > 0:
        pages = pages[:max_pages]

    zone_agree = Counter()
    zone_disagree = Counter()
    critical: list[dict] = []
    unmatched_html = 0
    unmatched_hocr = 0
    matched = 0

    detail_path = out_dir / f"audit_zones_{corpus}_detail.csv"
    with detail_path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(
            fh,
            fieldnames=[
                "page",
                "html_zone",
                "hocr_zone",
                "ratio",
                "x_offset",
                "html_text",
                "hocr_text",
                "flag",
            ],
        )
        w.writeheader()

        for hp, op in pages:
            page = hp.stem.split("_")[-1]
            html_lines = _kept(html_parse(hp, corpus))
            hocr_lines = _kept(hocr_parse(op, corpus))
            for h, o, ratio in _align(html_lines, hocr_lines):
                if h is None:
                    unmatched_hocr += 1
                    w.writerow(
                        {
                            "page": page,
                            "html_zone": "",
                            "hocr_zone": o["zone"],
                            "ratio": "",
                            "x_offset": o.get("x_offset", ""),
                            "html_text": "",
                            "hocr_text": o["text"][:120],
                            "flag": "hocr_only",
                        }
                    )
                    continue
                if o is None:
                    unmatched_html += 1
                    w.writerow(
                        {
                            "page": page,
                            "html_zone": h["zone"],
                            "hocr_zone": "",
                            "ratio": "",
                            "x_offset": "",
                            "html_text": h["text"][:120],
                            "hocr_text": "",
                            "flag": "html_only",
                        }
                    )
                    continue

                matched += 1
                key = (h["zone"], o["zone"])
                flag = ""
                if h["zone"] == o["zone"]:
                    zone_agree[h["zone"]] += 1
                else:
                    zone_disagree[key] += 1
                    flag = "disagree"
                    if key in _CRITICAL:
                        flag = "critical"
                        critical.append(
                            {
                                "page": page,
                                "html_zone": h["zone"],
                                "hocr_zone": o["zone"],
                                "ratio": f"{ratio:.2f}",
                                "x_offset": o.get("x_offset", ""),
                                "text": h["text"][:100],
                            }
                        )

                w.writerow(
                    {
                        "page": page,
                        "html_zone": h["zone"],
                        "hocr_zone": o["zone"],
                        "ratio": f"{ratio:.3f}",
                        "x_offset": o.get("x_offset", ""),
                        "html_text": h["text"][:120],
                        "hocr_text": o["text"][:120],
                        "flag": flag,
                    }
                )

    n_agree = sum(zone_agree.values())
    n_disagree = sum(zone_disagree.values())
    return {
        "corpus": corpus,
        "pages": len(pages),
        "matched": matched,
        "agree": n_agree,
        "disagree": n_disagree,
        "agree_pct": (100.0 * n_agree / matched) if matched else 0.0,
        "unmatched_html": unmatched_html,
        "unmatched_hocr": unmatched_hocr,
        "critical_n": len(critical),
        "critical": critical,
        "top_disagree": zone_disagree.most_common(12),
        "detail": detail_path,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--corpus", choices=["nl", "bl", "all"], default="all")
    ap.add_argument(
        "--pages",
        type=int,
        default=30,
        help="Max pages per corpus (0 = all)",
    )
    ap.add_argument(
        "--out",
        type=Path,
        default=Path(__file__).resolve().parent / "audit_out",
    )
    ap.add_argument(
        "--corrections",
        action="store_true",
        help="Also report hybrid HTML zone corrections (step 2)",
    )
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    corpora = ["nl", "bl"] if args.corpus == "all" else [args.corpus]
    print("Hybrid step 1 — HTML ↔ hOCR zone audit")
    print(f"pages/corpus={args.pages or 'all'}  out={args.out}\n")

    for c in corpora:
        s = audit_corpus(c, args.pages, args.out)
        print(f"=== {c.upper()}  pages={s['pages']} ===")
        print(
            f"  matched={s['matched']}  agree={s['agree']} ({s['agree_pct']:.1f}%)  "
            f"disagree={s['disagree']}"
        )
        print(
            f"  unmatched html={s['unmatched_html']}  hocr={s['unmatched_hocr']}  "
            f"critical entry↔footnote={s['critical_n']}"
        )
        if s["top_disagree"]:
            print("  top disagreements (html→hocr):")
            for (a, b), n in s["top_disagree"]:
                print(f"    {n:4d}  {a:16s} → {b}")
        if s["critical"]:
            print("  critical samples:")
            for row in s["critical"][:8]:
                print(
                    f"    p{row['page']}  html={row['html_zone']} hocr={row['hocr_zone']} "
                    f"x={row['x_offset']}  {row['text']!r}"
                )
        print(f"  detail → {s['detail']}")

        if args.corrections:
            cfg = CORPORA[c]
            pages = _page_pairs(cfg)
            if args.pages > 0:
                pages = pages[: args.pages]
            n_changed = 0
            by_reason: Counter = Counter()
            samples = []
            for hp, op in pages:
                summary = correct_page_pair(hp, op, c)
                n_changed += summary["n_changed"]
                for ch in summary["changes"]:
                    by_reason[ch["reason"]] += 1
                    if len(samples) < 6:
                        samples.append((summary["page"], ch))
            print(f"  hybrid corrections: {n_changed} lines")
            for reason, n in by_reason.most_common():
                print(f"    {n:4d}  {reason}")
            for page, ch in samples:
                print(
                    f"    p{page}  {ch['from']}→{ch['to']}  "
                    f"y={ch['y_frac'] and round(ch['y_frac'], 2)}  {ch['text']!r}"
                )
        print()


if __name__ == "__main__":
    main()
