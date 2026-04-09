"""CLI entry point for lemma-extractor.

Usage
-----
    uv run python main.py tag     [--corpus nl|bl|all] [--verbose]
    uv run python main.py extract [--corpus nl|bl|all] [--verbose]
    uv run python main.py verify  [--corpus nl|bl|all] [--verbose]
    uv run python main.py all     [--corpus nl|bl|all] [--verbose]

Paths are resolved relative to the workspace root (one level up from this file).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Workspace root = parent of the lemma_extractor/ project directory
ROOT = Path(__file__).resolve().parent.parent

CORPORA = {
    "nl": {
        "excel":      ROOT / "dijkstra_bew" / "schutte_binnenland_met_lemma.xlsx",
        "xml_src":    ROOT / "schutte_binnenland" / "schutte_binnenland_output_tagged.xml",
        "xml_tagged": ROOT / "schutte_binnenland" / "schutte_binnenland_output_tagged.xml",
        "out_dir":    ROOT / "lemmas" / "nl",
        "prefix":     "nl",
        "corpus":     "nl",
    },
    "bl": {
        "excel":      ROOT / "dijkstra_bew" / "schutte_buitenland_met_lemma.xlsx",
        "xml_src":    ROOT / "schutte_buitenland" / "schutte_buitenland_output.xml",
        "xml_tagged": ROOT / "schutte_buitenland" / "schutte_buitenland_output_tagged.xml",
        "out_dir":    ROOT / "lemmas" / "bl",
        "prefix":     "bl",
        "corpus":     "bl",
    },
}


def cmd_tag(corpus_keys: list[str], verbose: bool) -> None:
    from lemma_extractor.read_excel import load_lemmas
    from lemma_extractor.tag_xml import tag_corpus

    for key in corpus_keys:
        c = CORPORA[key]
        print(f"\n=== tag [{key}] ===")
        print(f"  Excel  : {c['excel']}")
        print(f"  Source : {c['xml_src']}")
        print(f"  Output : {c['xml_tagged']}")
        lemmas = load_lemmas(c["excel"])
        print(f"  Loaded {len(lemmas)} lemmas from Excel")
        stats = tag_corpus(c["xml_src"], lemmas, c["xml_tagged"], verbose=verbose)
        print(
            f"  Tagged: {stats['tagged']}  "
            f"Skipped: {stats['skipped']}  "
            f"Not found: {len(stats['not_found'])}"
        )
        if stats["not_found"]:
            print(f"  Not found schuttenr: {stats['not_found'][:20]}")


def cmd_extract(corpus_keys: list[str], verbose: bool) -> None:
    from lemma_extractor.read_excel import load_lemmas
    from lemma_extractor.extract_lemmas import extract_lemmas

    for key in corpus_keys:
        c = CORPORA[key]
        print(f"\n=== extract [{key}] ===")
        print(f"  Tagged XML : {c['xml_tagged']}")
        print(f"  Output dir : {c['out_dir']}")
        if not c["xml_tagged"].exists():
            print(f"  ERROR: tagged XML not found — run 'tag' first")
            continue
        lemmas = load_lemmas(c["excel"])
        stats = extract_lemmas(
            c["xml_tagged"], lemmas, c["out_dir"], c["prefix"],
            corpus=c["corpus"], verbose=verbose,
        )
        print(
            f"  Extracted: {stats['extracted']}  "
            f"No-meta: {len(stats['no_meta'])}  "
            f"Empty: {len(stats['empty'])}"
        )


def cmd_verify(corpus_keys: list[str], verbose: bool) -> None:
    from lemma_extractor.read_excel import load_lemmas
    from lemma_extractor.verify import verify, report

    for key in corpus_keys:
        c = CORPORA[key]
        print(f"\n=== verify [{key}] ===")
        lemmas = load_lemmas(c["excel"])
        stats = verify(c["out_dir"], lemmas, c["prefix"], verbose=verbose)
        print(report(stats, lemmas, c["prefix"]))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extract individual lemma XML files from Schutte RNVB corpora"
    )
    parser.add_argument(
        "command",
        choices=["tag", "extract", "verify", "all"],
        help="Action to perform",
    )
    parser.add_argument(
        "--corpus",
        choices=["nl", "bl", "all"],
        default="all",
        help="Which corpus to process (default: all)",
    )
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    keys = ["nl", "bl"] if args.corpus == "all" else [args.corpus]

    if args.command in ("tag", "all"):
        cmd_tag(keys, args.verbose)
    if args.command in ("extract", "all"):
        cmd_extract(keys, args.verbose)
    if args.command in ("verify", "all"):
        cmd_verify(keys, args.verbose)


if __name__ == "__main__":
    main()

