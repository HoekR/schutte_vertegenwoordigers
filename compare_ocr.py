"""
compare_ocr.py — compare Tesseract hOCR text against the original HTML source text.

For each page, extracts plain text from both sources and reports:
  - overall character-level similarity (difflib ratio)
  - lines present only in HTML (possibly OCR errors in original)
  - lines present only in hOCR (possibly improvements)
  - low-confidence words (x_wconf < threshold) from hOCR

Output: tab-separated summary (one row per page) to stdout, plus a
        verbose diff report written to compare_ocr_report.txt.

Usage:
  python compare_ocr.py                      # both corpora
  python compare_ocr.py --corpus bl          # BL only
  python compare_ocr.py --threshold 70       # flag words with confidence < 70 (default 80)
  python compare_ocr.py --pages 5            # only first N pages per corpus (quick test)
"""

import argparse
import difflib
import re
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent

CORPORA = {
    "bl": {
        "html_dir": SCRIPT_DIR / "schutte_buitenland",
        "ocr_dir":  SCRIPT_DIR / "schutte_buitenland_ocr",
        "prefix":   "schutte_buitenlandsevertegenwoordigersinnederland",
    },
    "nl": {
        "html_dir": SCRIPT_DIR / "schutte_binnenland",
        "ocr_dir":  SCRIPT_DIR / "schutte_binnenland_ocr",
        "prefix":   "schutte_nederlandsevertegenwoordigersinbuitenland",
    },
}


# ── text extraction ────────────────────────────────────────────────────────────


def html_to_text(path: Path) -> str:
    """Extract plain text from original source HTML (latin-1, <br>-separated)."""
    raw = path.read_bytes().decode("latin-1", errors="replace")
    # replace <br> with newline, strip all other tags
    text = re.sub(r'<br\s*/?>', '\n', raw, flags=re.IGNORECASE)
    text = re.sub(r'<[^>]+>', '', text)
    lines = [l.strip() for l in text.splitlines()]
    return "\n".join(l for l in lines if l)



def hocr_to_text(path: Path, conf_threshold: int) -> tuple[str, list]:
    """Return (plain_text, low_confidence_words) from an hOCR file."""
    raw = path.read_text(encoding="utf-8", errors="replace")

    # Split on each ocr_line class marker; each chunk contains exactly the
    # ocrx_word spans belonging to that line (nested span regex would hit the
    # first word's </span> instead of the line's </span>).
    word_pat = re.compile(r"class='ocrx_word'[^>]*>([^<]+)<")
    lines = []
    for chunk in re.split(r"class='ocr_line'", raw)[1:]:
        words = [w.strip() for w in word_pat.findall(chunk) if w.strip()]
        if words:
            lines.append(" ".join(words))

    # Low-confidence words (scanned globally in document order)
    low_conf = []
    for m in re.finditer(
        r"class='ocrx_word'[^>]*title='[^']*x_wconf\s+(\d+)[^']*'>([^<]+)<",
        raw
    ):
        conf, word = int(m.group(1)), m.group(2).strip()
        if conf < conf_threshold and word:
            low_conf.append((word, conf))

    return "\n".join(lines), low_conf


# ── comparison ─────────────────────────────────────────────────────────────────

def compare_page(html_path: Path, hocr_path: Path, conf_threshold: int) -> dict:
    html_text = html_to_text(html_path)
    hocr_text, low_conf = hocr_to_text(hocr_path, conf_threshold)

    html_lines = html_text.splitlines()
    hocr_lines = hocr_text.splitlines()

    ratio = difflib.SequenceMatcher(None, html_text, hocr_text).ratio()

    # Lines only in HTML or only in hOCR
    html_only, hocr_only = [], []
    matcher = difflib.SequenceMatcher(None, html_lines, hocr_lines)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag in ("replace", "delete"):
            html_only.extend(html_lines[i1:i2])
        if tag in ("replace", "insert"):
            hocr_only.extend(hocr_lines[j1:j2])

    return {
        "stem":       html_path.stem,
        "ratio":      ratio,
        "html_lines": len(html_lines),
        "hocr_lines": len(hocr_lines),
        "html_only":  html_only,
        "hocr_only":  hocr_only,
        "low_conf":   low_conf,
    }


# ── main ───────────────────────────────────────────────────────────────────────

def run(corpora, conf_threshold, max_pages, report_path):
    summary_rows = []
    report_lines = []

    for key, cfg in corpora.items():
        html_dir = cfg["html_dir"]
        ocr_dir  = cfg["ocr_dir"]
        prefix   = cfg["prefix"]

        html_files = sorted(html_dir.glob(f"{prefix}_*.html"))
        if max_pages:
            html_files = html_files[:max_pages]

        print(f"\n=== {key.upper()} — {len(html_files)} pages ===")
        report_lines.append(f"\n{'='*60}\n{key.upper()}\n{'='*60}")

        for html_path in html_files:
            hocr_path = ocr_dir / (html_path.stem + ".hocr")
            if not hocr_path.exists():
                print(f"  skip {html_path.name} (no hOCR)")
                continue

            result = compare_page(html_path, hocr_path, conf_threshold)
            pct = result["ratio"] * 100
            n_low = len(result["low_conf"])
            print(f"  {result['stem'][-8:]}  similarity={pct:.1f}%  "
                  f"html_only={len(result['html_only'])}  "
                  f"hocr_only={len(result['hocr_only'])}  "
                  f"low_conf_words={n_low}")

            summary_rows.append("\t".join([
                result["stem"], f"{pct:.1f}",
                str(len(result["html_only"])), str(len(result["hocr_only"])),
                str(n_low),
            ]))

            # verbose report
            report_lines.append(f"\n--- {result['stem']} (similarity {pct:.1f}%) ---")
            if result["html_only"]:
                report_lines.append("  HTML only (original, absent in hOCR):")
                for l in result["html_only"][:10]:
                    report_lines.append(f"    < {l}")
            if result["hocr_only"]:
                report_lines.append("  hOCR only (new OCR, absent in HTML):")
                for l in result["hocr_only"][:10]:
                    report_lines.append(f"    > {l}")
            if result["low_conf"]:
                report_lines.append(f"  Low-confidence words (< {conf_threshold}%):")
                for word, conf in result["low_conf"][:20]:
                    report_lines.append(f"    '{word}' ({conf}%)")

    # Write report
    report_path.write_text("\n".join(report_lines), encoding="utf-8")
    print(f"\nDetailed report written to {report_path}")

    # Write TSV summary
    tsv_path = report_path.with_suffix(".tsv")
    header = "page\tsimilarity\thtml_only_lines\thocr_only_lines\tlow_conf_words"
    tsv_path.write_text(header + "\n" + "\n".join(summary_rows), encoding="utf-8")
    print(f"Summary TSV written to {tsv_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", choices=["bl", "nl", "both"], default="both")
    parser.add_argument("--threshold", type=int, default=80,
                        help="Flag words with confidence below this % (default: 80)")
    parser.add_argument("--pages", type=int, default=0,
                        help="Only process first N pages per corpus (0 = all)")
    args = parser.parse_args()

    selected = CORPORA if args.corpus == "both" else {args.corpus: CORPORA[args.corpus]}
    report_path = SCRIPT_DIR / "compare_ocr_report.txt"
    run(selected, args.threshold, args.pages or None, report_path)
