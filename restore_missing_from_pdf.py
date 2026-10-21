"""
restore_missing_from_pdf.py — fill HTML / scan / hOCR gaps from pdf_sourcs/schuttepdfs.tar.gz.

For every page that exists as PDF but not as HTML (or scan / hOCR), extract the
PDF, write Huygens-style ``…_<NNNN>.html`` (pdftotext -layout + ``<br>``), a
JPEG scan (~810×1282), and Tesseract hOCR (nld, 2× upscale).

Usage:
  uv run python restore_missing_from_pdf.py              # both corpora, all gaps
  uv run python restore_missing_from_pdf.py --corpus nl
  uv run python restore_missing_from_pdf.py --skip-ocr   # html + scan only
  uv run python restore_missing_from_pdf.py --dry-run
  uv run python restore_missing_from_pdf.py --pages 11,15,17
"""

from __future__ import annotations

import argparse
import re
import subprocess
import tarfile
import tempfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
TAR = SCRIPT_DIR / "pdf_sourcs" / "schuttepdfs.tar.gz"

CORPORA = {
    "nl": {
        "prefix": "schutte_nederlandsevertegenwoordigersinbuitenland",
        "tar_dir": "schutte/2/originelen/pdf",
        "html_dir": "schutte_binnenland",
        "scan_dir": "schutte_binnenland_scans",
        "ocr_dir": "schutte_binnenland_ocr",
    },
    "bl": {
        "prefix": "schutte_buitenlandsevertegenwoordigersinnederland",
        "tar_dir": "schutte/1/originelen/pdf",
        "html_dir": "schutte_buitenland",
        "scan_dir": "schutte_buitenland_scans",
        "ocr_dir": "schutte_buitenland_ocr",
    },
}


def _nums(directory: Path, prefix: str, suffix: str) -> set[int]:
    out: set[int] = set()
    if not directory.exists():
        return out
    for p in directory.glob(f"{prefix}_*.{suffix}"):
        m = re.search(rf"_(\d+)\.{re.escape(suffix)}$", p.name)
        if m:
            out.add(int(m.group(1)))
    return out


_PDF_INDEX: dict[str, dict[int, str]] | None = None


def _pdf_index(tar_path: Path) -> dict[str, dict[int, str]]:
    """Build corpus → {page: tar member} once (gzip listing is slow)."""
    global _PDF_INDEX
    if _PDF_INDEX is not None:
        return _PDF_INDEX
    print(f"Indexing {tar_path.name} …", flush=True)
    out: dict[str, dict[int, str]] = {k: {} for k in CORPORA}
    with tarfile.open(tar_path, "r:gz") as tf:
        for name in tf.getnames():
            for key, cfg in CORPORA.items():
                prefix = cfg["prefix"]
                if f"/{prefix}_" not in name or not name.endswith(".pdf"):
                    continue
                m = re.search(rf"{re.escape(prefix)}_(\d+)\.pdf$", name)
                if m:
                    out[key][int(m.group(1))] = name
    _PDF_INDEX = out
    for key, pages in out.items():
        print(f"  {key}: {len(pages)} PDFs", flush=True)
    return out


def _pdf_nums(tar_path: Path, corpus: str) -> dict[int, str]:
    return _pdf_index(tar_path)[corpus]


def pdf_to_html(pdf: Path) -> str:
    text = subprocess.check_output(
        ["pdftotext", "-layout", "-enc", "UTF-8", str(pdf), "-"],
        text=True,
    )
    lines = [ln.rstrip() for ln in text.splitlines()]
    while lines and not lines[-1]:
        lines.pop()
    return "<br>".join(lines) + ("\n" if lines else "")


def extract_pdfs_batch(
    tar_path: Path, members: dict[int, str], dest_dir: Path, prefix: str
) -> None:
    """Extract many PDFs in one tar pass (gzip re-open per file is too slow)."""
    want = set(members.values())
    dest_dir.mkdir(parents=True, exist_ok=True)
    print(f"Extracting {len(want)} PDFs from archive …", flush=True)
    with tarfile.open(tar_path, "r:gz") as tf:
        for member in tf:
            if member.name not in want:
                continue
            m = re.search(rf"{re.escape(prefix)}_(\d+)\.pdf$", member.name)
            if not m:
                continue
            dest = dest_dir / f"{prefix}_{int(m.group(1)):04d}.pdf"
            src = tf.extractfile(member)
            if src is None:
                continue
            dest.write_bytes(src.read())


def render_scan(pdf: Path, dest_jpg: Path, work: Path) -> None:
    stem = work / dest_jpg.stem
    subprocess.run(
        [
            "pdftoppm",
            "-jpeg",
            "-jpegopt",
            "quality=85",
            "-scale-to-x",
            "810",
            "-scale-to-y",
            "1282",
            str(pdf),
            str(stem),
        ],
        check=True,
        capture_output=True,
    )
    produced = Path(f"{stem}-1.jpg")
    if not produced.exists():
        matches = sorted(work.glob(f"{dest_jpg.stem}*.jpg"))
        if not matches:
            raise FileNotFoundError(f"pdftoppm produced no jpg for {pdf.name}")
        produced = matches[0]
    dest_jpg.parent.mkdir(parents=True, exist_ok=True)
    dest_jpg.write_bytes(produced.read_bytes())


def ocr_hocr(jpg: Path, out_stem: Path, work: Path) -> None:
    scaled = work / f"{jpg.stem}_scaled.png"
    r = subprocess.run(
        ["convert", str(jpg), "-resize", "200%", str(scaled)],
        capture_output=True,
    )
    if r.returncode != 0:
        raise RuntimeError(r.stderr.decode() or "convert failed")
    out_stem.parent.mkdir(parents=True, exist_ok=True)
    r = subprocess.run(
        ["tesseract", str(scaled), str(out_stem), "-l", "nld", "hocr"],
        capture_output=True,
    )
    if r.returncode != 0:
        raise RuntimeError(
            (r.stderr.decode() or r.stdout.decode() or "tesseract failed").strip()
        )


def restore_corpus(
    key: str,
    *,
    pages: set[int] | None,
    skip_ocr: bool,
    dry_run: bool,
) -> dict[str, int]:
    cfg = CORPORA[key]
    prefix = cfg["prefix"]
    html_dir = SCRIPT_DIR / cfg["html_dir"]
    scan_dir = SCRIPT_DIR / cfg["scan_dir"]
    ocr_dir = SCRIPT_DIR / cfg["ocr_dir"]

    pdf_map = _pdf_nums(TAR, key)
    have_html = _nums(html_dir, prefix, "html")
    have_scan = _nums(scan_dir, prefix, "jpg")
    have_ocr = _nums(ocr_dir, prefix, "hocr")

    # Restore anything missing among html/scan/(ocr) that exists as PDF.
    candidates = sorted(pdf_map)
    if pages is not None:
        candidates = [n for n in candidates if n in pages]

    todo = [
        n
        for n in candidates
        if n not in have_html
        or n not in have_scan
        or (not skip_ocr and n not in have_ocr)
    ]

    counts = {
        "todo": len(todo),
        "html": 0,
        "scan": 0,
        "ocr": 0,
        "skip": 0,
        "error": 0,
    }
    print(f"\n=== {key.upper()} — {len(todo)} page(s) to restore ===", flush=True)
    if dry_run:
        for n in todo[:40]:
            flags = []
            if n not in have_html:
                flags.append("html")
            if n not in have_scan:
                flags.append("scan")
            if not skip_ocr and n not in have_ocr:
                flags.append("ocr")
            print(f"  would restore {n:04d} ({','.join(flags)})", flush=True)
        if len(todo) > 40:
            print(f"  … +{len(todo) - 40} more", flush=True)
        return counts

    with tempfile.TemporaryDirectory(prefix=f"schutte_restore_{key}_") as tmp:
        work = Path(tmp)
        pdf_dir = work / "pdfs"
        members = {n: pdf_map[n] for n in todo}
        extract_pdfs_batch(TAR, members, pdf_dir, prefix)

        for i, n in enumerate(todo, 1):
            stem = f"{prefix}_{n:04d}"
            pdf_path = pdf_dir / f"{stem}.pdf"
            html_path = html_dir / f"{stem}.html"
            jpg_path = scan_dir / f"{stem}.jpg"
            hocr_stem = ocr_dir / stem
            hocr_path = Path(str(hocr_stem) + ".hocr")
            try:
                if not pdf_path.exists():
                    raise FileNotFoundError(f"PDF not extracted: {stem}")
                need_html = not html_path.exists()
                need_scan = not jpg_path.exists()
                need_ocr = (not skip_ocr) and (
                    not hocr_path.exists() or hocr_path.stat().st_size < 1000
                )
                if not (need_html or need_scan or need_ocr):
                    counts["skip"] += 1
                    continue

                if need_html:
                    html_path.write_text(pdf_to_html(pdf_path), encoding="utf-8")
                    counts["html"] += 1

                if need_scan or need_ocr:
                    if need_scan or not jpg_path.exists():
                        render_scan(pdf_path, jpg_path, work)
                        if need_scan:
                            counts["scan"] += 1

                if need_ocr:
                    ocr_hocr(jpg_path, hocr_stem, work)
                    counts["ocr"] += 1

                print(
                    f"[{i}/{len(todo)}] {stem}: "
                    f"html={'+' if need_html else '.'} "
                    f"scan={'+' if need_scan else '.'} "
                    f"ocr={'+' if need_ocr else ('.' if not skip_ocr else '-')}",
                    flush=True,
                )
            except Exception as exc:  # noqa: BLE001 — continue batch
                counts["error"] += 1
                print(f"[{i}/{len(todo)}] {stem}: ERROR {exc}", flush=True)

    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", choices=("nl", "bl", "all"), default="all")
    parser.add_argument(
        "--pages",
        help="Comma-separated page numbers (limits restore to these)",
    )
    parser.add_argument("--skip-ocr", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not TAR.exists():
        raise SystemExit(f"PDF archive not found: {TAR}")

    page_set: set[int] | None = None
    if args.pages:
        page_set = {int(x.strip()) for x in args.pages.split(",") if x.strip()}

    keys = ("nl", "bl") if args.corpus == "all" else (args.corpus,)
    totals = {"html": 0, "scan": 0, "ocr": 0, "error": 0, "todo": 0}
    for key in keys:
        c = restore_corpus(
            key, pages=page_set, skip_ocr=args.skip_ocr, dry_run=args.dry_run
        )
        for k in totals:
            totals[k] += c.get(k, 0)

    print(
        f"\nDone. todo={totals['todo']} html+={totals['html']} "
        f"scan+={totals['scan']} ocr+={totals['ocr']} errors={totals['error']}"
    )


if __name__ == "__main__":
    main()
